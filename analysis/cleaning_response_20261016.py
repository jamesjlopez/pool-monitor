"""Offline cleaning-response analysis; never polls or changes pump calibration.

Run from the project root with .venv/bin/python analysis/cleaning_response_20261016.py.
Uses frozen inputs in logs/flow-investigation-2026-10-16, captured October 16.
Source timestamps, rather than poll timestamps, place observations around events.
"""

import csv
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from monitor.hydraulic_quality import classify_hydraulic_rows

OUTPUT = ROOT / "logs/flow-investigation-2026-10-16"
ZONE = ZoneInfo("America/Chicago")


def summarize(samples):
    if not samples:
        return {"samples": 0}
    return {
        "samples": len(samples),
        "first_source": samples[0]["flow_source"],
        "last_source": samples[-1]["flow_source"],
        "median_gpm": median(s["flow_gpm"] for s in samples),
        "min_gpm": min(s["flow_gpm"] for s in samples),
        "max_gpm": max(s["flow_gpm"] for s in samples),
        "median_reported_system_psi": median(s["reported_system_psi"] for s in samples),
        "median_watts": median(s["watts"] for s in samples),
    }


def main():
    with (OUTPUT / "input-metrics.csv").open(newline="") as source:
        rows = list(csv.DictReader(source))
    audit = classify_hydraulic_rows(rows)
    samples, excluded = [], []
    for row, classification in zip(rows, audit):
        if classification["hydraulic_quality"] != "verified":
            continue
        program, ref = row["active_program"], row["active_reference"]
        setpoint = float(row["active_setpoint"] or 0)
        flow, watts = float(row["flow_gph"]), float(row["power_watts"])
        speed = float(row["motor_speed_pct"] or 0)
        if flow <= 0 or watts <= 0 or not program or not ref or not setpoint:
            continue
        # This investigation covers the two observed percent-speed programs.
        # Reject the known post-restart high-program/low-load transition.
        if ref != "3" or not math.isclose(speed * 10, setpoint) or watts < 150:
            excluded.append({"poll_time": row["timestamp"], "reason": "unsettled or unmatched operating context"})
            continue
        parts = row["telemetry_version"].split("|")
        pressure_source, flow_source = (datetime.fromtimestamp(int(parts[i]), ZONE) for i in (1, 3))
        samples.append({
            "poll_time": row["timestamp"],
            "pressure_source": pressure_source.isoformat(),
            "flow_source": flow_source.isoformat(),
            "program": program, "reference": ref, "setpoint": setpoint,
            "motor_speed_pct": speed, "flow_gpm": flow / 60,
            "reported_system_psi": float(row["pressure_psi"]), "watts": watts,
        })
    groups = defaultdict(list)
    for sample in samples:
        groups[(sample["program"], sample["reference"], sample["setpoint"])].append(sample)
    references = []
    daily = []
    for key, group in sorted(groups.items()):
        values = sorted(s["flow_gpm"] for s in group)
        references.append({"program": key[0], "reference": key[1], "setpoint": key[2],
                           "samples": len(group), "p90_gpm": values[math.floor((len(values) - 1) * .9)]})
        days = defaultdict(list)
        for sample in group:
            days[sample["flow_source"][:10]].append(sample)
        daily.extend({"date": day, "program": key[0], **summarize(day_samples)}
                     for day, day_samples in sorted(days.items()))
    # Combine simultaneous actions: they are one intervention, not independent labels.
    events = defaultdict(list)
    for event in json.loads((OUTPUT / "input-maintenance.json").read_text()):
        events[datetime.fromisoformat(event["ts"]).astimezone(ZONE)].append(event)
    ordered = sorted(events)
    responses = []
    for i, time in enumerate(ordered):
        before = max(time - timedelta(hours=24), ordered[i - 1] if i else time - timedelta(hours=24))
        after = min(time + timedelta(hours=24), ordered[i + 1] if i + 1 < len(ordered) else time + timedelta(hours=24))
        by_program = []
        for key, group in sorted(groups.items()):
            # Both source fields must fall on the same side of the intervention.
            pre = [s for s in group if before <= min(datetime.fromisoformat(s[f]) for f in ("pressure_source", "flow_source"))
                   and max(datetime.fromisoformat(s[f]) for f in ("pressure_source", "flow_source")) < time]
            post = [s for s in group if time + timedelta(minutes=10) <= min(datetime.fromisoformat(s[f]) for f in ("pressure_source", "flow_source"))
                    and max(datetime.fromisoformat(s[f]) for f in ("pressure_source", "flow_source")) < after]
            by_program.append({"program": key[0], "reference": key[1], "setpoint": key[2],
                               "pre": summarize(pre), "post": summarize(post),
                               "first_three_post": post[:3], "last_three_pre": pre[-3:]})
        responses.append({"time": time.isoformat(), "actions": [e["kind"] for e in events[time]],
                          "notes": [e.get("notes", "") for e in events[time]],
                          "window_start": before.isoformat(), "window_end": after.isoformat(),
                          "by_program": by_program})
    with (OUTPUT / "verified-steady-readings.csv").open("w", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=list(samples[0]))
        writer.writeheader()
        writer.writerows(samples)
    result = {"input_first_poll": rows[0]["timestamp"], "input_last_poll": rows[-1]["timestamp"],
              "polls": len(rows), "quality_counts": dict(Counter(a["hydraulic_quality"] for a in audit)),
              "steady_samples": len(samples), "excluded_transitions": excluded,
              "references": references, "daily": daily, "cleaning_responses": responses,
              "limitations": ["Flow and system pressure are pump estimates, not external sensor measurements.",
                              "Motor percentage is reported; physical shaft RPM is not independently measured.",
                              "Ten-minute settling exclusion is an analysis convention.",
                              "Post windows stop at the next logged intervention; unlogged changes remain possible.",
                              "No configuration, pump controls, maintenance records or production state changed."]}
    (OUTPUT / "analysis.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("input_last_poll", "polls", "steady_samples", "excluded_transitions", "references")}, indent=2))


if __name__ == "__main__":
    main()

"""Reproduce the September 20 basket-cleaning comparison without polling the pump.

Run from the project root: .venv/bin/python analysis/skimmer_cleaning_20260920.py
Outputs contain only paired new hydraulic updates; poll time is not sample time.
"""

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from monitor.hydraulic_quality import classify_hydraulic_rows

ZONE = ZoneInfo("America/Chicago")
CLEANED = datetime(2026, 9, 20, 12, 7, tzinfo=ZONE)


def main():
    with (ROOT / "logs/metrics.csv").open(newline="") as source:
        rows = list(csv.DictReader(source))
    samples = []
    daily = defaultdict(list)
    for row, audit in zip(rows, classify_hydraulic_rows(rows)):
        if audit["hydraulic_quality"] != "verified":
            continue
        parts = row["telemetry_version"].split("|")
        pressure_at = datetime.fromtimestamp(int(parts[1]), ZONE)
        flow_at = datetime.fromtimestamp(int(parts[3]), ZONE)
        flow = float(row["flow_gph"])
        if flow <= 0 or not row["active_setpoint"]:
            continue
        sample = {
            "poll_time": row["timestamp"],
            "pressure_source_time": pressure_at.isoformat(),
            "flow_source_time": flow_at.isoformat(),
            "program": row["active_program"],
            "reference": row["active_reference"],
            "setpoint": row["active_setpoint"],
            "flow_gph": flow,
            "reported_pressure_psi": float(row["pressure_psi"]),
            "power_watts": float(row["power_watts"]),
            "after_cleaning": min(pressure_at, flow_at) > CLEANED,
            "settled_after_cleaning": min(pressure_at, flow_at).timestamp() >= CLEANED.timestamp() + 600,
        }
        samples.append(sample)
        daily[(flow_at.date().isoformat(), sample["program"], sample["reference"], sample["setpoint"])].append(sample)
    output = ROOT / "logs/skimmer-cleaning-2026-09-20"
    output.mkdir(exist_ok=True)
    with (output / "verified-readings.csv").open("w", newline="") as destination:
        if samples:
            writer = csv.DictWriter(destination, fieldnames=list(samples[0]))
            writer.writeheader()
            writer.writerows(samples)
    summary = []
    for (day, program, reference, setpoint), group in sorted(daily.items()):
        summary.append({
            "date": day, "program": program, "reference": reference,
            "setpoint": setpoint, "samples": len(group),
            "median_flow_gph": median(s["flow_gph"] for s in group),
            "median_reported_pressure_psi": median(s["reported_pressure_psi"] for s in group),
            "median_power_watts": median(s["power_watts"] for s in group),
        })
    (output / "daily-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({
        "cleaned_at": CLEANED.isoformat(),
        "polls": len(rows), "verified_running_samples": len(samples),
        "post_cleaning": [s for s in samples if s["after_cleaning"]],
        "output_directory": str(output),
    }, indent=2))


if __name__ == "__main__":
    main()

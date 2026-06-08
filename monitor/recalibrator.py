"""
Recalibrator — detects filter-cleaning events and auto-updates baselines in config.yaml.

Detection pattern:
  The filter gradually clogs → ratio rises above clean baseline → user cleans →
  ratio drops sharply back to near-baseline level.

We detect this as a two-phase signal:
  1. "Was dirty": at least ELEVATED_MIN_COUNT of the last ELEVATED_HISTORY_SIZE readings
     were elevated above baseline * ELEVATED_THRESHOLD.
  2. "Now clean": CLEAN_READINGS_REQUIRED consecutive readings below CLEAN_LANDING * baseline.

When both conditions are met, we compute the new clean baseline (mean of clean readings),
update config.yaml in-place, and return a RecalibrationEvent.

First-run note: the recalibrator requires an existing baseline in config.yaml to operate.
The very first cleaning must be calibrated manually — after that, subsequent cleanings are
auto-detected.
"""

import json
import logging
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .profiles import is_bypass_or_drain_profile
from .types import PumpStatus

log = logging.getLogger(__name__)

# A reading is "elevated" (filter dirty) if ratio exceeds this multiple of baseline
ELEVATED_THRESHOLD   = 1.20
# We require at least this many elevated readings in the history window before watching for a drop
ELEVATED_MIN_COUNT   = 3
# How many recent readings to scan for the "was dirty" signal
ELEVATED_HISTORY_SIZE = 12   # ~6 hours at 30-min polls
# A reading is "clean landing" if ratio is at or near baseline
CLEAN_LANDING        = 1.12  # within 12% above baseline counts as clean
# Consecutive clean-landing readings required to confirm a cleaning event
CLEAN_READINGS_REQUIRED = 3
# Clean samples should be stable; bypass/drain events can create a single ultra-low outlier.
CLEAN_WINDOW_MAX_SPREAD = 0.20
# Don't bother updating config.yaml if baseline shift is trivial
MIN_BASELINE_CHANGE  = 0.003


@dataclass
class RecalibrationEvent:
    speed_mode: str
    old_baseline: float
    new_baseline: float
    baseline_updated: bool   # False when new ≈ old (cleaning confirmed but no config change)
    timestamp: str


class Recalibrator:
    def __init__(self, config_path: Path, log_path: Path):
        self._config_path = config_path
        self._log_path = log_path
        # Rolling history of recent ratios (as multiples of baseline) per speed mode
        self._history:       dict[str, deque] = defaultdict(lambda: deque(maxlen=ELEVATED_HISTORY_SIZE))
        # Accumulating window of consecutive near-baseline readings
        self._clean_window:  dict[str, deque] = defaultdict(lambda: deque(maxlen=CLEAN_READINGS_REQUIRED))

    def observe(self, status: PumpStatus, config: dict) -> Optional[RecalibrationEvent]:
        """
        Observe one pump reading. Returns a RecalibrationEvent if a cleaning is confirmed,
        otherwise None. Mutates config in-place on a baseline update.
        """
        if not status.is_running or status.rpm == 0 or status.flow_gph <= 0:
            return None

        ratio = status.watts_per_gph
        if ratio is None or ratio <= 0:
            return None

        speed_mode = status.speed_mode
        if speed_mode not in ("low", "high"):
            return None

        speed_key = "low_speed" if speed_mode == "low" else "high_speed"
        baseline = (
            config.get("thresholds", {})
            .get(speed_key, {})
            .get("baseline_watts_per_gph")
        )
        if not baseline:
            return None

        if is_bypass_or_drain_profile(status, baseline):
            log.info(
                "Ignoring bypass/drain-like telemetry for recalibration [%s]: "
                "RPM=%d, %.0fW, %.0f GPH, ratio=%.4f",
                speed_mode, status.rpm, status.power_watts, status.flow_gph, ratio,
            )
            self._clean_window[speed_mode].clear()
            return None

        pct_of_baseline = ratio / baseline
        self._history[speed_mode].append(pct_of_baseline)

        if pct_of_baseline <= CLEAN_LANDING:
            self._clean_window[speed_mode].append(ratio)
        else:
            self._clean_window[speed_mode].clear()
            return None

        if len(self._clean_window[speed_mode]) < CLEAN_READINGS_REQUIRED:
            remaining = CLEAN_READINGS_REQUIRED - len(self._clean_window[speed_mode])
            log.debug(
                "Clean-landing candidate [%s]: ratio=%.4f (%.0f%% of baseline), %d more reading(s) to confirm",
                speed_mode, ratio, pct_of_baseline * 100, remaining,
            )
            return None

        # Confirm the "was dirty" condition from recent history
        history = list(self._history[speed_mode])
        # Exclude the most recent CLEAN_READINGS_REQUIRED readings (those are the clean ones)
        pre_clean_history = history[:-CLEAN_READINGS_REQUIRED]
        elevated_count = sum(1 for x in pre_clean_history if x >= ELEVATED_THRESHOLD)

        if elevated_count < ELEVATED_MIN_COUNT:
            log.debug(
                "Clean readings detected [%s] but insufficient elevated history "
                "(%d/%d elevated readings in pre-clean window) — not a cleaning event",
                speed_mode, elevated_count, ELEVATED_MIN_COUNT,
            )
            self._clean_window[speed_mode].clear()
            return None

        clean_ratios = list(self._clean_window[speed_mode])
        low = min(clean_ratios)
        high = max(clean_ratios)
        if low <= 0 or (high - low) / low > CLEAN_WINDOW_MAX_SPREAD:
            log.info(
                "Clean-landing readings [%s] are too unstable for recalibration "
                "(min %.4f, max %.4f) — ignoring event",
                speed_mode, low, high,
            )
            self._clean_window[speed_mode].clear()
            return None

        new_baseline = round(
            sum(clean_ratios) / len(clean_ratios),
            4,
        )
        self._clean_window[speed_mode].clear()
        self._history[speed_mode].clear()  # reset so we don't re-trigger immediately

        baseline_updated = abs(new_baseline - baseline) >= MIN_BASELINE_CHANGE
        event = RecalibrationEvent(
            speed_mode=speed_mode,
            old_baseline=baseline,
            new_baseline=new_baseline,
            baseline_updated=baseline_updated,
            timestamp=datetime.now().isoformat(timespec="seconds"),
        )

        if baseline_updated:
            if self._update_config(speed_key, new_baseline):
                config["thresholds"][speed_key]["baseline_watts_per_gph"] = new_baseline
                log.info(
                    "Filter cleaning detected [%s] — baseline updated: %.4f → %.4f W/GPH",
                    speed_mode, baseline, new_baseline,
                )
            else:
                event.baseline_updated = False
        else:
            log.info(
                "Filter cleaning detected [%s] — baseline unchanged (%.4f W/GPH, delta < threshold)",
                speed_mode, baseline,
            )

        self._log_event(event)
        return event

    def _update_config(self, speed_key: str, new_baseline: float) -> bool:
        """Rewrite baseline_watts_per_gph in config.yaml, preserving all other content."""
        try:
            text = self._config_path.read_text()
        except OSError as e:
            log.error("Cannot read config for recalibration: %s", e)
            return False

        lines = text.splitlines(keepends=True)
        in_section = False
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        for i, line in enumerate(lines):
            if re.match(rf"^\s+{re.escape(speed_key)}:\s*$", line):
                in_section = True
                continue

            if in_section:
                m = re.match(r"^(\s+baseline_watts_per_gph:\s*)[0-9.]+", line)
                if m:
                    lines[i] = f"{m.group(1)}{new_baseline}    # auto-recalibrated {stamp}\n"
                    self._config_path.write_text("".join(lines))
                    return True

                if re.match(r"^\s{2}\S", line) and not re.match(r"^\s{4}", line):
                    in_section = False

        log.error("Could not locate baseline_watts_per_gph for %s in config.yaml", speed_key)
        return False

    def _log_event(self, event: RecalibrationEvent) -> None:
        try:
            existing = (
                json.loads(self._log_path.read_text()) if self._log_path.exists() else []
            )
        except (json.JSONDecodeError, OSError):
            existing = []
        existing.append(
            {
                "ts": event.timestamp,
                "speed_mode": event.speed_mode,
                "old_baseline": event.old_baseline,
                "new_baseline": event.new_baseline,
                "baseline_updated": event.baseline_updated,
            }
        )
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_path.write_text(json.dumps(existing[-50:], indent=2))

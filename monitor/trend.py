"""
TrendAnalyzer — fits a linear trend to recent readings and warns before the filter
hits the alert threshold.

Reads metrics.csv, computes % above baseline per reading, fits a least-squares line
per speed mode, and extrapolates to when the ratio will cross the alert threshold.

Returns a TrendWarning if a crossing is projected within WARN_DAYS.
"""

import csv
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

WARN_DAYS = 3.0         # warn if crossing projected within this many days
MIN_READINGS = 6        # minimum data points needed to fit a meaningful trend
LOOKBACK_DAYS = 7       # only use readings from the past week


@dataclass
class TrendWarning:
    speed_mode: str
    days_to_warn: float
    current_pct: float
    alert_pct: float

    @property
    def message(self) -> str:
        return (
            f"Filter trending toward alert threshold [{self.speed_mode} speed]: "
            f"currently +{self.current_pct:.1f}% above baseline, "
            f"projected to reach +{self.alert_pct}% in ~{self.days_to_warn:.1f} day(s). "
            f"Consider rinsing filter proactively."
        )


def _least_squares(xs: list, ys: list) -> tuple[float, float]:
    n = len(xs)
    if n < 2:
        return 0.0, sum(ys) / max(n, 1)
    sx  = sum(xs)
    sy  = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0, sy / n
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope, intercept


class TrendAnalyzer:
    def __init__(self, metrics_path: Path):
        self._path = metrics_path

    def check(self, config: dict) -> Optional[TrendWarning]:
        """
        Return the most urgent TrendWarning if any speed mode is projected to hit
        its alert threshold within WARN_DAYS, or None.
        """
        rows = self._load_recent()
        if not rows:
            return None

        thresholds = config.get("thresholds", {})
        warnings: list[TrendWarning] = []

        for speed_mode, speed_key in (("low", "low_speed"), ("high", "high_speed")):
            cfg = thresholds.get(speed_key, {})
            baseline = cfg.get("baseline_watts_per_gph")
            alert_pct = cfg.get("alert_ratio_pct", 150)
            if not baseline:
                continue

            mode_rows = [r for r in rows if r["mode"] == speed_mode and r["ratio"] is not None]
            if len(mode_rows) < MIN_READINGS:
                continue

            t0 = mode_rows[0]["ts"]
            xs = [(r["ts"] - t0).total_seconds() / 3600 for r in mode_rows]
            ys = [((r["ratio"] / baseline) - 1) * 100 for r in mode_rows]

            slope, intercept = _least_squares(xs, ys)

            if slope <= 0:
                continue  # trend is flat or improving

            current_pct = ys[-1]
            if current_pct >= alert_pct:
                continue  # already alarming — engine handles this

            x_now = xs[-1]
            hours_to_warn = (alert_pct - (slope * x_now + intercept)) / slope
            days_to_warn = hours_to_warn / 24

            if 0 < days_to_warn <= WARN_DAYS:
                warnings.append(
                    TrendWarning(
                        speed_mode=speed_mode,
                        days_to_warn=round(days_to_warn, 1),
                        current_pct=round(current_pct, 1),
                        alert_pct=alert_pct,
                    )
                )
                log.info(
                    "Trend warning [%s]: +%.1f%% now, projected to reach +%d%% in %.1f days",
                    speed_mode, current_pct, alert_pct, days_to_warn,
                )

        if not warnings:
            return None
        return min(warnings, key=lambda w: w.days_to_warn)

    def _load_recent(self) -> list:
        if not self._path.exists():
            return []
        cutoff = datetime.now() - timedelta(days=LOOKBACK_DAYS)
        rows = []
        try:
            with open(self._path, newline="") as f:
                for r in csv.DictReader(f):
                    try:
                        ts = datetime.fromisoformat(r["timestamp"])
                        if ts < cutoff:
                            continue
                        ratio = float(r["watts_per_gph"]) if r.get("watts_per_gph") else None
                        rows.append({"ts": ts, "ratio": ratio, "mode": r.get("speed_mode", "")})
                    except (ValueError, KeyError):
                        continue
        except OSError:
            pass
        return rows

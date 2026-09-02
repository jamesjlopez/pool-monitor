"""
TrendAnalyzer — fits a linear trend to recent readings and warns before the filter
hits the alert threshold.

Reads metrics.csv, computes % above baseline per reading, summarizes each speed
mode into daily medians, fits a robust Theil-Sen line, and extrapolates to when
the ratio will cross the alert threshold.

Returns a TrendWarning if a crossing is projected within WARN_DAYS.
"""

import csv
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Optional

log = logging.getLogger(__name__)

WARN_DAYS = 3.0         # warn if crossing projected within this many days
MIN_READING_DAYS = 4    # minimum independent days needed for a forecast
LOOKBACK_DAYS = 7       # only use readings from the past week
OUTLIER_JUMP_PCT = 15.0
OUTLIER_CONFIRM_PCT = 15.0


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


def _daily_medians(rows: list[dict], baseline: float) -> list[tuple[datetime, float]]:
    """Give each calendar day one vote, so retries and short spikes cannot dominate."""
    by_day: dict = {}
    for row in rows:
        by_day.setdefault(row["ts"].date(), []).append(
            ((row["ratio"] / baseline) - 1) * 100
        )
    return [
        (datetime.combine(day, datetime.min.time()), median(values))
        for day, values in sorted(by_day.items())
    ]


def _confirmed_daily_medians(
    daily: list[tuple[datetime, float]],
) -> list[tuple[datetime, float]]:
    """Discard a large daily jump unless the following day corroborates it."""
    isolated = []
    for index, sample in enumerate(daily):
        if 0 < index < len(daily) - 1:
            previous, following = daily[index - 1][1], daily[index + 1][1]
            if (
                abs(sample[1] - median((previous, following))) > OUTLIER_JUMP_PCT
                and abs(following - previous) <= OUTLIER_CONFIRM_PCT
            ):
                log.info("Discarding isolated daily trend deviation: %+.1f%%", sample[1])
                continue
        isolated.append(sample)

    confirmed = isolated[:3]
    index = 3
    while index < len(isolated):
        _, pct = isolated[index]
        recent = [value for _, value in confirmed[-3:]]
        if abs(pct - median(recent)) <= OUTLIER_JUMP_PCT:
            confirmed.append(isolated[index])
            index += 1
            continue

        next_day = isolated[index + 1] if index + 1 < len(isolated) else None
        if next_day and abs(next_day[1] - pct) <= OUTLIER_CONFIRM_PCT:
            confirmed.extend((isolated[index], next_day))
            index += 2
        else:
            log.info("Discarding unconfirmed daily trend deviation: %+.1f%%", pct)
            index += 1
    return confirmed


def _theil_sen(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Robust linear fit: a single abnormal day cannot pull the forecast forward."""
    slopes = [
        (ys[j] - ys[i]) / (xs[j] - xs[i])
        for i in range(len(xs))
        for j in range(i + 1, len(xs))
        if xs[j] != xs[i]
    ]
    if not slopes:
        return 0.0, median(ys)
    slope = median(slopes)
    return slope, median([y - slope * x for x, y in zip(xs, ys)])


class TrendAnalyzer:
    def __init__(self, metrics_path: Path):
        self._path = metrics_path

    def check(self, config: dict, active_mode: Optional[str] = None) -> Optional[TrendWarning]:
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
            if active_mode is not None and speed_mode != active_mode:
                continue
            cfg = thresholds.get(speed_key, {})
            baseline = cfg.get("baseline_watts_per_gph")
            alert_pct = cfg.get("alert_ratio_pct", 150)
            if not baseline:
                continue

            mode_rows = [r for r in rows if r["mode"] == speed_mode and r["ratio"] is not None]
            daily = _confirmed_daily_medians(_daily_medians(mode_rows, baseline))
            if len(daily) < MIN_READING_DAYS:
                continue

            t0 = daily[0][0]
            xs = [(ts - t0).total_seconds() / 86400 for ts, _ in daily]
            ys = [pct for _, pct in daily]

            slope, intercept = _theil_sen(xs, ys)

            if slope <= 0:
                continue  # trend is flat or improving

            current_pct = ys[-1]
            if current_pct >= alert_pct:
                continue  # already alarming — engine handles this

            x_now = xs[-1]
            days_to_warn = (alert_pct - (slope * x_now + intercept)) / slope

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

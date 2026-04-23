#!/usr/bin/env python3
"""
Pool Monitor Engine
Speed-aware anomaly detection using watts-per-GPH ratio as a proxy for filter pressure.

Since the pump's digital interface reports RPM, watts, and flow (GPH) but not PSI,
we detect filter clogging by watching the watts/GPH efficiency ratio. A clogged filter
increases backpressure, which reduces flow while the pump maintains or increases power —
causing the ratio to rise above a calibrated baseline.

Calibrate baseline_watts_per_gph in config.yaml after observing the pump on a clean filter.
Until calibrated, the engine uses conservative flow-drop heuristics only.
"""

import logging
import time
from collections import deque
from typing import Optional

from .types import AlertLevel, EngineResult, PumpStatus

log = logging.getLogger(__name__)

# Default speed profile ratios (from Pentair IntelliFlo spec data, clean filter).
# These are overridden by config.yaml baseline_watts_per_gph once user calibrates.
_DEFAULT_BASELINES = {
    "low": 0.083,   # ~150W / 1800 GPH at ~1000 RPM
    "high": 0.143,  # ~600W / 4200 GPH at ~2800 RPM
}


class Engine:
    def __init__(self, config: dict):
        self._cfg = config["thresholds"]
        self._window_size = self._cfg.get("consecutive_readings_required", 3)
        self._grace_seconds = self._cfg.get("startup_grace_seconds", 120)
        self._pump_start_time: Optional[float] = None
        self._window: deque[EngineResult] = deque(maxlen=self._window_size)
        self._zero_flow_streak: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def seed_window(self, levels: list) -> None:
        """Pre-populate rolling window from persisted state (for cron --once mode)."""
        self._window.clear()
        for level in levels[-self._window_size:]:
            self._window.append(EngineResult(level=level, reason="(restored)", speed_mode=""))

    def mark_pump_start(self):
        """Call when the pump transitions from off→on to start the grace period."""
        self._pump_start_time = time.time()
        self._window.clear()
        self._zero_flow_streak = 0
        log.info("Pump start detected — grace period active for %ds", self._grace_seconds)

    def process(self, status: PumpStatus) -> EngineResult:
        """Evaluate one reading and return the effective alert level."""
        if not status.is_running or status.rpm == 0:
            self._window.clear()
            self._zero_flow_streak = 0
            # Contradictory reading: API says not running / RPM=0 but reports non-zero
            # watts or flow — likely a transitional API glitch. Re-poll to get a valid read.
            if status.rpm == 0 and (status.power_watts > 0 or status.flow_gph > 0):
                return EngineResult(
                    level=AlertLevel.NORMAL,
                    reason="Contradictory reading (RPM=0 but watts/flow non-zero) — awaiting valid read",
                    speed_mode="off",
                    pending_elevated=True,
                )
            return EngineResult(level=AlertLevel.NORMAL, reason="Pump not running",
                                speed_mode="off")

        if self._in_grace_period():
            elapsed = time.time() - self._pump_start_time
            remaining = self._grace_seconds - elapsed
            return EngineResult(
                level=AlertLevel.NORMAL,
                reason=f"Startup grace period ({remaining:.0f}s remaining)",
                speed_mode=status.speed_mode,
            )

        raw_result = self._evaluate(status)

        # Zero-flow: suppress the first reading (could be a transient/API glitch) and
        # trigger fast-confirm polling. A second consecutive zero-flow escalates to CRITICAL.
        if status.flow_gph <= 0 and raw_result.level > AlertLevel.NORMAL:
            self._zero_flow_streak += 1
            if self._zero_flow_streak >= 2:
                return EngineResult(
                    level=AlertLevel.CRITICAL,
                    reason=(
                        f"Confirmed zero flow ({self._zero_flow_streak} consecutive readings) — "
                        f"pump blocked or air-locked"
                    ),
                    speed_mode=raw_result.speed_mode,
                    consecutive_count=self._zero_flow_streak,
                )
            return EngineResult(
                level=AlertLevel.NORMAL,
                reason=f"Zero flow detected — awaiting confirmation (1/2)",
                speed_mode=raw_result.speed_mode,
                pending_elevated=True,
            )

        self._zero_flow_streak = 0
        self._window.append(raw_result)
        return self._apply_window(raw_result)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _in_grace_period(self) -> bool:
        if self._pump_start_time is None:
            return False
        return (time.time() - self._pump_start_time) < self._grace_seconds

    def _speed_cfg(self, speed_mode: str) -> dict:
        key = "low_speed" if speed_mode == "low" else "high_speed"
        return self._cfg[key]

    def _evaluate(self, status: PumpStatus) -> EngineResult:
        """Single-reading evaluation (before rolling window is applied)."""
        scfg = self._speed_cfg(status.speed_mode)
        ratio = status.watts_per_gph
        baseline = scfg.get("baseline_watts_per_gph") or _DEFAULT_BASELINES.get(status.speed_mode)

        level = AlertLevel.NORMAL
        reason = "Normal operation"

        if ratio is None or status.flow_gph <= 0:
            # Zero flow while running is immediately suspicious — bypass rolling window
            return EngineResult(
                level=AlertLevel.WARN,
                reason="Zero flow detected — pump may be blocked or air-locked",
                speed_mode=status.speed_mode,
                watts_per_gph=ratio,
                baseline_watts_per_gph=baseline,
                consecutive_count=1,
            )

        if baseline:
            deviation_pct = ((ratio - baseline) / baseline) * 100
            emergency_pct = scfg.get("emergency_ratio_pct", 80)
            alert_pct = scfg.get("alert_ratio_pct", 30)

            if deviation_pct >= emergency_pct:
                level = AlertLevel.CRITICAL
                reason = (
                    f"Extreme backpressure: efficiency ratio {ratio:.4f} W/GPH is "
                    f"{deviation_pct:.0f}% above baseline {baseline:.4f} — "
                    f"filter critically clogged or blockage"
                )
            elif deviation_pct >= alert_pct:
                level = AlertLevel.WARN
                reason = (
                    f"Elevated backpressure: efficiency ratio {ratio:.4f} W/GPH is "
                    f"{deviation_pct:.0f}% above baseline {baseline:.4f} — "
                    f"consider rinsing filter"
                )
            else:
                reason = f"Normal — ratio {ratio:.4f} W/GPH ({deviation_pct:+.0f}% vs baseline)"
        else:
            # No calibrated baseline — fall back to absolute flow heuristics
            low_flow_threshold = 1200 if status.speed_mode == "low" else 2500
            if status.flow_gph < low_flow_threshold and status.power_watts > 200:
                level = AlertLevel.WARN
                reason = (
                    f"Low flow ({status.flow_gph:.0f} GPH) with high power "
                    f"({status.power_watts:.0f}W) — possible blockage. "
                    f"Calibrate baseline_watts_per_gph in config.yaml for better detection."
                )
            else:
                reason = (
                    f"Flow {status.flow_gph:.0f} GPH, power {status.power_watts:.0f}W "
                    f"(no baseline calibrated — set baseline_watts_per_gph in config.yaml)"
                )

        return EngineResult(
            level=level,
            reason=reason,
            speed_mode=status.speed_mode,
            watts_per_gph=ratio,
            baseline_watts_per_gph=baseline,
        )

    def _apply_window(self, latest: EngineResult) -> EngineResult:
        """
        Require consecutive_readings_required readings above threshold before alerting.
        This prevents single-point noise from triggering notifications.
        """
        if len(self._window) < self._window_size:
            # Still warming up — suppress alerts until we have enough data
            if latest.level > AlertLevel.NORMAL:
                return EngineResult(
                    level=AlertLevel.NORMAL,
                    reason=f"Accumulating readings ({len(self._window)}/{self._window_size}) — {latest.reason}",
                    speed_mode=latest.speed_mode,
                    watts_per_gph=latest.watts_per_gph,
                    baseline_watts_per_gph=latest.baseline_watts_per_gph,
                    consecutive_count=len(self._window),
                    pending_elevated=True,
                )
            return latest

        levels = [r.level for r in self._window]
        count = len(self._window)

        if all(l >= AlertLevel.CRITICAL for l in levels):
            return EngineResult(
                level=AlertLevel.CRITICAL,
                reason=latest.reason,
                speed_mode=latest.speed_mode,
                watts_per_gph=latest.watts_per_gph,
                baseline_watts_per_gph=latest.baseline_watts_per_gph,
                consecutive_count=count,
            )
        if all(l >= AlertLevel.WARN for l in levels):
            return EngineResult(
                level=AlertLevel.WARN,
                reason=latest.reason,
                speed_mode=latest.speed_mode,
                watts_per_gph=latest.watts_per_gph,
                baseline_watts_per_gph=latest.baseline_watts_per_gph,
                consecutive_count=count,
            )
        return EngineResult(
            level=AlertLevel.NORMAL,
            reason=latest.reason,
            speed_mode=latest.speed_mode,
            watts_per_gph=latest.watts_per_gph,
            baseline_watts_per_gph=latest.baseline_watts_per_gph,
            consecutive_count=count,
        )

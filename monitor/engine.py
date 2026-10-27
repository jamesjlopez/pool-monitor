#!/usr/bin/env python3
"""
Pool Monitor Engine
Speed-aware hydraulic monitoring using direct pressure and independent flow loss.

The pump reports pressure (PSI), power, and flow (GPH). A sustained high pressure
or a sustained flow drop from a known-clean program baseline triggers a warning.
Pressure alone can escalate to CRITICAL; flow loss remains a warning-only signal
until its calibration has accumulated more clean-filter evidence.
"""

import logging
import time
from collections import deque
from dataclasses import replace
from typing import Optional

from .profiles import is_high_program_low_speed_profile
from .types import AlertLevel, EngineResult, PumpStatus

log = logging.getLogger(__name__)


class Engine:
    def __init__(self, config: dict):
        self._cfg = config["thresholds"]
        self._window_size = self._cfg.get("consecutive_readings_required", 3)
        self._grace_seconds = self._cfg.get("startup_grace_seconds", 120)
        self._pump_start_time: Optional[float] = None
        self._window: deque[EngineResult] = deque(maxlen=self._window_size)
        self._zero_flow_streak: int = 0
        # Pentair returns a source timestamp for each device snapshot.  Fast
        # confirmation polls must not turn one unchanged cloud snapshot into
        # several independent observations.
        self._last_telemetry_version: Optional[str] = None
        self._last_pressure_telemetry_version: Optional[str] = None
        self._last_flow_telemetry_version: Optional[str] = None
        self._pressure_mapping_verified = config.get("emergency_shutoff", {}).get("pressure_mapping_verified", False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_baseline(self, speed_mode: str, new_baseline: float) -> None:
        """Update the in-memory baseline after an auto-recalibration event."""
        self._speed_cfg(speed_mode)["baseline_watts_per_gph"] = new_baseline

    def seed_window(self, levels: list) -> None:
        """Pre-populate rolling window from persisted state (for cron --once mode)."""
        self._window.clear()
        for level in levels[-self._window_size:]:
            self._window.append(EngineResult(level=level, reason="(restored)", speed_mode=""))

    def seed_telemetry_version(self, version: Optional[str]) -> None:
        """Restore the most recently evaluated cloud snapshot across --once runs."""
        self._last_telemetry_version = version

    def seed_hydraulic_telemetry_versions(self, pressure: Optional[str], flow: Optional[str]) -> None:
        self._last_pressure_telemetry_version = pressure
        self._last_flow_telemetry_version = flow

    def mark_pump_start(self):
        """Call when the pump transitions from off→on to start the grace period."""
        self._pump_start_time = time.time()
        self._zero_flow_streak = 0
        log.info("Pump start detected — grace period active for %ds", self._grace_seconds)

    def reset_alert_history(self) -> None:
        """Discard a completed alert sequence after an emergency stop succeeds."""
        self._window.clear()
        self._zero_flow_streak = 0

    def process(self, status: PumpStatus) -> EngineResult:
        """Evaluate one reading and return the effective alert level."""
        if not status.is_running:
            self._zero_flow_streak = 0
            return EngineResult(level=AlertLevel.NORMAL, reason="Pump not running",
                                speed_mode="off")

        # The cloud can briefly report a running program with no workload.
        # Await a fresh source sample instead of treating pressure as RPM.
        if status.power_watts == 0:
            self._zero_flow_streak = 0
            return EngineResult(
                level=AlertLevel.NORMAL,
                reason=self._zero_telemetry_reason(status),
                speed_mode=status.speed_mode,
                pending_elevated=True,
            )

        if status.speed_mode not in ("low", "high"):
            return EngineResult(
                level=AlertLevel.NORMAL,
                reason="Active pump program is unknown — awaiting attributable telemetry",
                speed_mode="unknown",
                pending_elevated=True,
            )

        if self._in_grace_period():
            elapsed = time.time() - self._pump_start_time
            remaining = self._grace_seconds - elapsed
            return EngineResult(
                level=AlertLevel.NORMAL,
                reason=f"Startup grace period ({remaining:.0f}s remaining)",
                speed_mode=status.speed_mode,
            )

        if is_high_program_low_speed_profile(status):
            return EngineResult(
                level=AlertLevel.NORMAL,
                reason=(
                    "High-speed program is reporting a low-speed/low-load profile — "
                    "awaiting a stable telemetry read"
                ),
                speed_mode=status.speed_mode,
                pending_elevated=True,
            )

        if not self._hydraulics_are_fresh(status):
            return EngineResult(AlertLevel.NORMAL, "Pentair pressure/flow telemetry timestamp unchanged — awaiting newer hydraulic data", speed_mode=status.speed_mode, telemetry_fresh=False)

        raw_result = self._evaluate(status)

        telemetry_version = status.telemetry_version
        if telemetry_version is not None:
            telemetry_version = str(telemetry_version)
            if telemetry_version == self._last_telemetry_version:
                pending = raw_result.level > AlertLevel.NORMAL
                return replace(
                    raw_result,
                    level=AlertLevel.NORMAL,
                    reason=(
                        "Pentair cloud telemetry timestamp unchanged — "
                        "awaiting a newer source sample"
                    ),
                    pending_elevated=pending,
                    telemetry_fresh=False,
                )
            self._last_telemetry_version = telemetry_version

        # Zero-flow while running is serious enough to warn immediately and trigger
        # fast-confirm polling. A second consecutive zero-flow escalates to CRITICAL.
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
                level=raw_result.level,
                reason=f"{raw_result.reason} — awaiting confirmation (1/2)",
                speed_mode=raw_result.speed_mode,
                watts_per_gph=raw_result.watts_per_gph,
                baseline_watts_per_gph=raw_result.baseline_watts_per_gph,
                consecutive_count=self._zero_flow_streak,
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

    def _hydraulics_are_fresh(self, status: PumpStatus) -> bool:
        pressure, flow = status.pressure_telemetry_version, status.flow_telemetry_version
        if pressure is None or flow is None:
            return True
        if self._last_pressure_telemetry_version is None or self._last_flow_telemetry_version is None:
            self.seed_hydraulic_telemetry_versions(pressure, flow)
            return True
        if pressure == self._last_pressure_telemetry_version or flow == self._last_flow_telemetry_version:
            return False
        self.seed_hydraulic_telemetry_versions(pressure, flow)
        return True

    def _zero_telemetry_reason(self, status: PumpStatus) -> str:
        snapshot = status.raw.get("fields_snapshot", {})
        appuse = snapshot.get("appuse")
        d25 = snapshot.get("d25")
        if appuse == "0" or d25 == "0":
            return (
                "Pentair cloud reports pump status switch disabled "
                "(d25/appuse=0) and zero telemetry — cannot calibrate"
            )
        return (
            "Pentair cloud reports running state but zero RPM/watts/flow — "
            "awaiting valid telemetry"
        )

    def _evaluate(self, status: PumpStatus) -> EngineResult:
        """Single-reading evaluation (before rolling window is applied)."""
        scfg = self._speed_cfg(status.speed_mode)
        ratio = status.watts_per_gph
        baseline = scfg.get("baseline_watts_per_gph") or None

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

        direct_signals = []
        pressure = status.pressure_psi
        if pressure is not None and self._pressure_mapping_verified:
            emergency_psi = scfg.get("emergency_psi")
            alert_psi = scfg.get("alert_psi")
            if emergency_psi is not None and pressure >= emergency_psi:
                level = AlertLevel.CRITICAL
                direct_signals.append(
                    f"Pressure {pressure:.2f} PSI is at/above the {emergency_psi:g} PSI emergency threshold"
                )
            elif alert_psi is not None and pressure >= alert_psi:
                level = AlertLevel.WARN
                direct_signals.append(
                    f"Pressure {pressure:.2f} PSI is at/above the {alert_psi:g} PSI alert threshold"
                )

        clean_flow = scfg.get("baseline_flow_gph")
        flow_alert_drop = scfg.get("flow_alert_drop_pct")
        if clean_flow and flow_alert_drop is not None:
            flow_drop_pct = (1 - status.flow_gph / clean_flow) * 100
            if flow_drop_pct >= flow_alert_drop:
                level = max(level, AlertLevel.WARN)
                direct_signals.append(
                    f"Flow loss {flow_drop_pct:.0f}% vs provisional clean baseline "
                    f"{clean_flow:.0f} GPH"
                )

        if pressure is not None:
            return EngineResult(
                level=level,
                reason="; ".join(direct_signals) if direct_signals else (
                    f"Normal — pressure {pressure:.2f} PSI and flow {status.flow_gph:.0f} GPH"
                ),
                speed_mode=status.speed_mode,
                watts_per_gph=ratio,
                baseline_watts_per_gph=baseline,
            )

        return EngineResult(
            level=level,
            reason="; ".join(direct_signals) or "Return flow monitored; pressure unavailable",
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
        # Window consensus is NORMAL but this reading is elevated — re-poll soon to
        # confirm or clear it rather than waiting the full interval.
        if latest.level > AlertLevel.NORMAL:
            return EngineResult(
                level=AlertLevel.NORMAL,
                reason=latest.reason,
                speed_mode=latest.speed_mode,
                watts_per_gph=latest.watts_per_gph,
                baseline_watts_per_gph=latest.baseline_watts_per_gph,
                consecutive_count=count,
                pending_elevated=True,
            )
        return EngineResult(
            level=AlertLevel.NORMAL,
            reason=latest.reason,
            speed_mode=latest.speed_mode,
            watts_per_gph=latest.watts_per_gph,
            baseline_watts_per_gph=latest.baseline_watts_per_gph,
            consecutive_count=count,
        )

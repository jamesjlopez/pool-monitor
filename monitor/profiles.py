"""Telemetry profile helpers shared by alerting and baseline learning."""

from .types import PumpStatus


HIGH_SPEED_MIN_RPM = 1500
MIN_NORMAL_LOAD_WATTS = 150
HIGH_FLOW_GPH = 3000
LOW_LOAD_RATIO = 0.05


def is_high_program_low_speed_profile(status: PumpStatus) -> bool:
    """Return True when the active high-speed program still reports low-speed load."""
    return (
        status.is_running
        and status.speed_mode == "high"
        and status.rpm < HIGH_SPEED_MIN_RPM
        and status.power_watts < MIN_NORMAL_LOAD_WATTS
    )


def is_bypass_or_drain_profile(status: PumpStatus, baseline: float | None = None) -> bool:
    """Detect hose/drain/bypass-like samples that are unsafe for recalibration."""
    ratio = status.watts_per_gph
    if not status.is_running or ratio is None:
        return False

    ratio_limit = LOW_LOAD_RATIO
    if baseline:
        ratio_limit = min(ratio_limit, baseline * 0.35)

    return (
        status.flow_gph >= HIGH_FLOW_GPH
        and status.power_watts < MIN_NORMAL_LOAD_WATTS
        and ratio <= ratio_limit
    ) or is_high_program_low_speed_profile(status)

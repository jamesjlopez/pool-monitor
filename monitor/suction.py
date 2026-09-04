"""Fresh-telemetry detection of likely suction-side restrictions."""

from collections import deque
from dataclasses import dataclass

from .types import PumpStatus


@dataclass(frozen=True)
class SuctionWarning:
    flow_drop_pct: float
    pressure_rise_psi: float
    kind: str

    @property
    def message(self) -> str:
        return (
            f"{self.kind.capitalize()} return-flow drop: {self.flow_drop_pct:.0f}% lower "
            f"with pressure {self.pressure_rise_psi:+.1f} PSI at the same pump program. "
            "Check the surface skimmer basket, pre-pump basket, pool water level, "
            "and visible air under the pump lid before servicing the filter."
        )


class SuctionRestrictionDetector:
    """Alert once per deterioration episode; stale cloud samples never enter history."""

    def __init__(self) -> None:
        self._readings: deque[PumpStatus] = deque(maxlen=4)
        self._alerted = False

    @staticmethod
    def _key(status: PumpStatus) -> tuple:
        return (status.speed_mode, status.raw.get("prog_name"), status.raw.get("active_reference"), status.raw.get("active_setpoint"))

    def observe(self, status: PumpStatus) -> SuctionWarning | None:
        if status.pressure_psi is None or status.flow_gph <= 0:
            return None
        if self._readings and self._key(self._readings[-1]) != self._key(status):
            self._readings.clear()
            self._alerted = False
        previous = self._readings[-1] if self._readings else None
        self._readings.append(status)
        if not previous or self._alerted:
            return None
        candidates = [(previous, "sudden")]
        if len(self._readings) >= 3:
            candidates.append((self._readings[0], "gradual"))
        for baseline, kind in candidates:
            drop = (1 - status.flow_gph / baseline.flow_gph) * 100
            rise = status.pressure_psi - baseline.pressure_psi
            if drop >= 20 and rise >= 0.5:
                self._alerted = True
                return SuctionWarning(round(drop, 1), round(rise, 2), kind)
        return None

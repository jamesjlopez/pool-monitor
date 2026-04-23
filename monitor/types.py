"""Shared dataclasses and enums used across all monitor modules."""

import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class AlertLevel(IntEnum):
    NORMAL = 0
    WARN = 1
    CRITICAL = 2

    def __str__(self) -> str:
        return self.name.lower()


@dataclass
class PumpStatus:
    rpm: int
    power_watts: float
    flow_gph: float
    is_running: bool
    timestamp: float = field(default_factory=time.time)
    speed_mode: str = ""   # "low" | "high" | "off" — auto-derived if empty
    raw: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.speed_mode:
            if not self.is_running or self.rpm == 0:
                self.speed_mode = "off"
            elif self.rpm < 1500:
                self.speed_mode = "low"
            else:
                self.speed_mode = "high"

    @property
    def watts_per_gph(self) -> Optional[float]:
        if self.flow_gph > 0:
            return self.power_watts / self.flow_gph
        return None


@dataclass
class EngineResult:
    level: AlertLevel
    reason: str
    speed_mode: str = ""
    watts_per_gph: Optional[float] = None
    baseline_watts_per_gph: Optional[float] = None
    consecutive_count: int = 0
    pending_elevated: bool = False  # raw reading was elevated but window not yet full

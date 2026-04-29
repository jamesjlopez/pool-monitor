"""
DataLogger — appends pump readings to a rolling CSV.

Logs one row per successful poll when the pump is running.
Prunes rows older than RETENTION_DAYS on every write.
ISO 8601 timestamps sort lexicographically, so the cutoff comparison is exact.
"""

import csv
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .types import EngineResult, PumpStatus

log = logging.getLogger(__name__)

RETENTION_DAYS = 30
COLUMNS = [
    "timestamp", "rpm", "power_watts", "flow_gph",
    "watts_per_gph", "speed_mode", "alert_level", "baseline_watts_per_gph",
]


class DataLogger:
    def __init__(self, path: Path):
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with open(path, "w", newline="") as f:
                csv.writer(f).writerow(COLUMNS)

    def log(self, status: PumpStatus, result: EngineResult) -> None:
        if not status.is_running or status.rpm == 0 or status.flow_gph <= 0 or status.power_watts == 0:
            return
        row = [
            datetime.now().isoformat(timespec="seconds"),
            status.rpm,
            round(status.power_watts, 1),
            round(status.flow_gph, 1),
            round(status.watts_per_gph, 4) if status.watts_per_gph else "",
            status.speed_mode,
            result.level.name.lower(),
            round(result.baseline_watts_per_gph, 4) if result.baseline_watts_per_gph else "",
        ]
        with open(self._path, "a", newline="") as f:
            csv.writer(f).writerow(row)
        self._prune()

    def _prune(self) -> None:
        cutoff = (datetime.now() - timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
        try:
            with open(self._path, newline="") as f:
                rows = list(csv.reader(f))
        except FileNotFoundError:
            return
        if len(rows) < 2:
            return
        header, data = rows[0], rows[1:]
        kept = [r for r in data if r and r[0] >= cutoff]
        if len(kept) < len(data):
            with open(self._path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(header)
                w.writerows(kept)
            log.debug("Pruned %d rows older than %d days", len(data) - len(kept), RETENTION_DAYS)

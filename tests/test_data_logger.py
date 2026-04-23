"""Tests for monitor/data_logger.py"""

import csv
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from monitor.data_logger import COLUMNS, DataLogger
from monitor.types import AlertLevel, EngineResult, PumpStatus


def make_status(rpm=1441, watts=403.0, gph=705.0, running=True, mode="low"):
    return PumpStatus(rpm=rpm, power_watts=watts, flow_gph=gph, is_running=running, speed_mode=mode)


def make_result(level=AlertLevel.NORMAL, baseline=0.570):
    return EngineResult(level=level, reason="test", speed_mode="low",
                        watts_per_gph=0.572, baseline_watts_per_gph=baseline)


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


class TestDataLogger:
    def test_creates_file_with_header(self, tmp_path):
        path = tmp_path / "metrics.csv"
        DataLogger(path)
        assert path.exists()
        with open(path) as f:
            header = f.readline().strip().split(",")
        assert header == COLUMNS

    def test_appends_row_for_running_pump(self, tmp_path):
        path = tmp_path / "metrics.csv"
        logger = DataLogger(path)
        logger.log(make_status(), make_result())
        rows = read_csv(path)
        assert len(rows) == 1
        assert rows[0]["speed_mode"] == "low"
        assert rows[0]["alert_level"] == "normal"
        assert float(rows[0]["rpm"]) == 1441

    def test_skips_pump_off(self, tmp_path):
        path = tmp_path / "metrics.csv"
        logger = DataLogger(path)
        logger.log(make_status(running=False, gph=0), make_result())
        assert len(read_csv(path)) == 0

    def test_skips_zero_flow(self, tmp_path):
        path = tmp_path / "metrics.csv"
        logger = DataLogger(path)
        logger.log(make_status(gph=0), make_result())
        assert len(read_csv(path)) == 0

    def test_multiple_rows(self, tmp_path):
        path = tmp_path / "metrics.csv"
        logger = DataLogger(path)
        for _ in range(5):
            logger.log(make_status(), make_result())
        assert len(read_csv(path)) == 5

    def test_prunes_old_rows(self, tmp_path):
        path = tmp_path / "metrics.csv"
        logger = DataLogger(path)

        # Write one old row directly (31 days ago)
        old_ts = (datetime.now() - timedelta(days=31)).isoformat(timespec="seconds")
        with open(path, "a", newline="") as f:
            csv.writer(f).writerow(
                [old_ts, 1441, 403, 705, 0.5716, "low", "normal", 0.570]
            )

        # Write a current row via logger (triggers prune)
        logger.log(make_status(), make_result())

        rows = read_csv(path)
        assert len(rows) == 1
        assert rows[0]["timestamp"] != old_ts

    def test_preserves_recent_rows_during_prune(self, tmp_path):
        path = tmp_path / "metrics.csv"
        logger = DataLogger(path)

        # Write 3 rows: one old, two recent
        old_ts = (datetime.now() - timedelta(days=31)).isoformat(timespec="seconds")
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            w.writerow([old_ts, 1441, 403, 705, 0.5716, "low", "normal", 0.570])

        logger.log(make_status(), make_result())
        logger.log(make_status(rpm=2020, watts=601, gph=854, mode="high"),
                   make_result(level=AlertLevel.WARN))

        rows = read_csv(path)
        assert len(rows) == 2
        assert rows[1]["alert_level"] == "warn"

    def test_warn_level_logged_correctly(self, tmp_path):
        path = tmp_path / "metrics.csv"
        logger = DataLogger(path)
        logger.log(make_status(), make_result(level=AlertLevel.WARN))
        rows = read_csv(path)
        assert rows[0]["alert_level"] == "warn"

    def test_critical_level_logged_correctly(self, tmp_path):
        path = tmp_path / "metrics.csv"
        logger = DataLogger(path)
        logger.log(make_status(), make_result(level=AlertLevel.CRITICAL))
        rows = read_csv(path)
        assert rows[0]["alert_level"] == "critical"

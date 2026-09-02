"""Tests for robust, mode-aware cleaning forecasts."""

import csv
from datetime import datetime, timedelta

from monitor.trend import TrendAnalyzer


def _config(alert_pct=30):
    return {
        "thresholds": {
            "low_speed": {
                "baseline_watts_per_gph": 0.1,
                "alert_ratio_pct": alert_pct,
            },
            "high_speed": {
                "baseline_watts_per_gph": 0.1,
                "alert_ratio_pct": alert_pct,
            },
        }
    }


def _write_metrics(path, values, mode="low", append=False):
    with path.open("a" if append else "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "watts_per_gph", "speed_mode"])
        if not append:
            writer.writeheader()
        start = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=len(values) - 1)
        for index, pct in enumerate(values):
            writer.writerow({
                "timestamp": (start + timedelta(days=index)).isoformat(),
                "watts_per_gph": 0.1 * (1 + pct / 100),
                "speed_mode": mode,
            })


def test_spike_day_does_not_create_imminent_cleaning_warning(tmp_path):
    """A one-day excursion must not pull a cleaning forecast forward."""
    metrics = tmp_path / "metrics.csv"
    _write_metrics(metrics, [10, 12, 14, 16, 18, 200])

    warning = TrendAnalyzer(metrics).check(_config())

    assert warning is None


def test_unconfirmed_latest_day_jump_is_discarded(tmp_path):
    """A new large deviation needs the following day's corroboration."""
    metrics = tmp_path / "metrics.csv"
    _write_metrics(metrics, [5, 6, 7, 29])

    warning = TrendAnalyzer(metrics).check(_config())

    assert warning is None


def test_unconfirmed_early_window_spike_is_discarded(tmp_path):
    metrics = tmp_path / "metrics.csv"
    _write_metrics(metrics, [0, 0, 100, 15])

    warning = TrendAnalyzer(metrics).check(_config())

    assert warning is None


def test_trend_only_considers_the_active_speed_mode(tmp_path):
    metrics = tmp_path / "metrics.csv"
    _write_metrics(metrics, [10, 12, 14, 16, 18, 20], mode="low")
    _write_metrics(metrics, [10, 15, 20, 25, 30, 35], mode="high", append=True)

    warning = TrendAnalyzer(metrics).check(_config(), active_mode="low")

    assert warning is None

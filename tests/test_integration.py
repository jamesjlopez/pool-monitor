"""
Integration tests — replay fixture sequences through the full stack.
No real pump or ntfy server required. Tests the end-to-end behavior
of client → engine → notifier with fixture data.
"""

from pathlib import Path

import pytest

from monitor.api_client import MockPentairClient
from monitor.engine import Engine
from monitor.notifier import NtfyNotifier
from monitor.runner import run_once
from monitor.types import AlertLevel

FIXTURES = Path(__file__).parent / "fixtures"

FULL_CONFIG = {
    "pump": {"host": "", "poll_interval_seconds": 60},
    "thresholds": {
        "startup_grace_seconds": 120,
        "consecutive_readings_required": 3,
        "alert_cooldown_minutes": 30,
        "low_speed": {
            "alert_psi": 12,
            "emergency_psi": 18,
            "baseline_watts_per_gph": 0.083,
            "alert_ratio_pct": 30,
            "emergency_ratio_pct": 80,
        },
        "high_speed": {
            "alert_psi": 20,
            "emergency_psi": 30,
            "baseline_watts_per_gph": 0.143,
            "alert_ratio_pct": 30,
            "emergency_ratio_pct": 80,
        },
    },
    "ntfy": {
        "server": "https://ntfy.sh",
        "topic": "test_pool_monitor",
        "priority_alert": "high",
        "priority_emergency": "urgent",
    },
    "emergency_shutoff": {"enabled": False, "consecutive_required": 5, "delay_seconds": 30},
    "logging": {"level": "DEBUG"},
}


def load_sequence(*fixture_names):
    """Build a MockPentairClient from multiple fixture files (played in order, then looping)."""
    from monitor.api_client import _fixture_to_status
    import json
    statuses = []
    for name in fixture_names:
        with open(FIXTURES / name) as f:
            statuses.append(_fixture_to_status(json.load(f)))
    return MockPentairClient(sequence=statuses)


class TestCleanFilterScenario:
    def test_3_clean_readings_no_alert(self, mocker):
        mock_post = mocker.patch("monitor.notifier.requests.post")
        client = load_sequence("pump_low_clean.json", "pump_low_clean.json", "pump_low_clean.json")
        engine = Engine(FULL_CONFIG)
        notifier = NtfyNotifier(FULL_CONFIG)

        for _ in range(3):
            result = run_once(client, engine, notifier, FULL_CONFIG)

        assert result.level == AlertLevel.NORMAL
        mock_post.assert_not_called()


class TestCloggedFilterScenario:
    def test_3_clogged_readings_trigger_warn(self, mocker):
        mock_resp = mocker.MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_post = mocker.patch("monitor.notifier.requests.post", return_value=mock_resp)

        # 3 clogged readings — should trigger WARN after window fills
        client = load_sequence(
            "pump_low_clogged.json",
            "pump_low_clogged.json",
            "pump_low_clogged.json",
        )
        engine = Engine(FULL_CONFIG)
        notifier = NtfyNotifier(FULL_CONFIG)

        results = [run_once(client, engine, notifier, FULL_CONFIG) for _ in range(3)]
        assert results[-1].level in (AlertLevel.WARN, AlertLevel.CRITICAL)
        assert mock_post.called


class TestStartupThenClog:
    def test_grace_suppresses_startup_priming_spike(self, mocker):
        mock_post = mocker.patch("monitor.notifier.requests.post")

        client = load_sequence("pump_startup.json", "pump_startup.json", "pump_startup.json")
        engine = Engine(FULL_CONFIG)
        engine.mark_pump_start()  # simulate pump just turned on
        notifier = NtfyNotifier(FULL_CONFIG)

        for _ in range(3):
            result = run_once(client, engine, notifier, FULL_CONFIG)

        assert result.level == AlertLevel.NORMAL
        mock_post.assert_not_called()


class TestMixedSequence:
    def test_clog_clears_after_clean_readings(self, mocker):
        mock_resp = mocker.MagicMock()
        mock_resp.raise_for_status.return_value = None
        mocker.patch("monitor.notifier.requests.post", return_value=mock_resp)

        # 2 clogged then 1 clean — window should not trigger
        client = load_sequence(
            "pump_low_clogged.json",
            "pump_low_clogged.json",
            "pump_low_clean.json",
        )
        engine = Engine(FULL_CONFIG)
        notifier = NtfyNotifier(FULL_CONFIG)

        results = [run_once(client, engine, notifier, FULL_CONFIG) for _ in range(3)]
        assert results[-1].level == AlertLevel.NORMAL


class TestHighSpeedScenario:
    def test_clean_high_speed_no_alert(self, mocker):
        mock_post = mocker.patch("monitor.notifier.requests.post")
        client = load_sequence(
            "pump_high_clean.json", "pump_high_clean.json", "pump_high_clean.json"
        )
        engine = Engine(FULL_CONFIG)
        notifier = NtfyNotifier(FULL_CONFIG)
        for _ in range(3):
            result = run_once(client, engine, notifier, FULL_CONFIG)
        assert result.level == AlertLevel.NORMAL
        mock_post.assert_not_called()

    def test_clogged_high_speed_triggers_alert(self, mocker):
        mock_resp = mocker.MagicMock()
        mock_resp.raise_for_status.return_value = None
        mocker.patch("monitor.notifier.requests.post", return_value=mock_resp)
        client = load_sequence(
            "pump_high_clogged.json", "pump_high_clogged.json", "pump_high_clogged.json"
        )
        engine = Engine(FULL_CONFIG)
        notifier = NtfyNotifier(FULL_CONFIG)
        results = [run_once(client, engine, notifier, FULL_CONFIG) for _ in range(3)]
        assert results[-1].level in (AlertLevel.WARN, AlertLevel.CRITICAL)

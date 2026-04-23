"""Tests for monitor/runner.py — run_once() integration with injected dependencies."""

import pytest

from monitor.api_client import MockPentairClient
from monitor.engine import Engine
from monitor.notifier import NtfyNotifier
from monitor.runner import run_once
from monitor.types import AlertLevel, PumpStatus

CALIBRATED_CONFIG = {
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
    "emergency_shutoff": {
        "enabled": False,
        "consecutive_required": 5,
        "delay_seconds": 30,
    },
    "logging": {"level": "DEBUG"},
}


def make_sequence(*statuses):
    return MockPentairClient(sequence=list(statuses))


class TestRunOnce:
    def test_returns_none_when_client_fails(self, mocker):
        client = MockPentairClient()  # empty → always returns None
        engine = Engine(CALIBRATED_CONFIG)
        notifier = mocker.MagicMock(spec=NtfyNotifier)
        result = run_once(client, engine, notifier, CALIBRATED_CONFIG)
        assert result is None
        notifier.send_alert.assert_not_called()

    def test_no_notification_on_normal_reading(self, mocker):
        clean = PumpStatus(rpm=1050, power_watts=148, flow_gph=1820, is_running=True)
        client = make_sequence(clean)
        engine = Engine(CALIBRATED_CONFIG)
        notifier = mocker.MagicMock(spec=NtfyNotifier)
        run_once(client, engine, notifier, CALIBRATED_CONFIG)
        notifier.send_alert.assert_not_called()

    def test_notification_on_warn_after_consecutive_readings(self, mocker):
        mock_resp = mocker.MagicMock()
        mock_resp.raise_for_status.return_value = None
        mocker.patch("monitor.notifier.requests.post", return_value=mock_resp)

        clogged = PumpStatus(rpm=1050, power_watts=195, flow_gph=500, is_running=True)
        engine = Engine(CALIBRATED_CONFIG)
        notifier = NtfyNotifier(CALIBRATED_CONFIG)

        # Need 3 consecutive readings to trigger
        for i in range(3):
            client = make_sequence(clogged)
            result = run_once(client, engine, notifier, CALIBRATED_CONFIG)

        assert result is not None
        assert result.level in (AlertLevel.WARN, AlertLevel.CRITICAL)

    def test_dry_run_suppresses_notification(self, mocker):
        mock_post = mocker.patch("monitor.notifier.requests.post")
        clogged = PumpStatus(rpm=1050, power_watts=195, flow_gph=500, is_running=True)
        engine = Engine({
            **CALIBRATED_CONFIG,
            "thresholds": {
                **CALIBRATED_CONFIG["thresholds"],
                "consecutive_readings_required": 1,
            }
        })
        notifier = NtfyNotifier(CALIBRATED_CONFIG)
        client = make_sequence(clogged)
        run_once(client, engine, notifier, CALIBRATED_CONFIG, dry_run=True)
        mock_post.assert_not_called()

    def test_emergency_shutoff_not_triggered_when_disabled(self, mocker):
        extreme = PumpStatus(rpm=1050, power_watts=300, flow_gph=200, is_running=True)
        mocker.patch("monitor.notifier.requests.post", return_value=mocker.MagicMock(
            raise_for_status=lambda: None
        ))
        engine = Engine({
            **CALIBRATED_CONFIG,
            "thresholds": {**CALIBRATED_CONFIG["thresholds"], "consecutive_readings_required": 1}
        })
        notifier = NtfyNotifier(CALIBRATED_CONFIG)
        client = make_sequence(extreme)
        # disabled in config — client.turn_off should never be called
        client.turn_off = mocker.MagicMock(return_value=True)
        run_once(client, engine, notifier, CALIBRATED_CONFIG)
        client.turn_off.assert_not_called()

"""Tests for monitor/runner.py — run_once() integration with injected dependencies."""

import pytest

from monitor.api_client import MockPentairClient
from monitor.engine import Engine
from monitor.notifier import NtfyNotifier
from monitor.runner import _check_trend, run_once
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
    def test_uses_supplied_status_without_a_second_cloud_request(self, mocker):
        status = PumpStatus(rpm=1050, power_watts=148, flow_gph=1820, is_running=True)
        client = mocker.MagicMock()
        engine = Engine(CALIBRATED_CONFIG)
        notifier = mocker.MagicMock(spec=NtfyNotifier)

        result = run_once(client, engine, notifier, CALIBRATED_CONFIG, status=status)

        assert result.level == AlertLevel.NORMAL
        client.get_status.assert_not_called()

    def test_duplicate_cloud_snapshot_does_not_recalibrate(self, mocker):
        status = PumpStatus(
            rpm=1050, power_watts=148, flow_gph=1820, is_running=True,
            telemetry_version="same-cloud-sample",
        )
        engine = Engine(CALIBRATED_CONFIG)
        notifier = mocker.MagicMock(spec=NtfyNotifier)
        recalibrator = mocker.MagicMock()
        recalibrator.observe.return_value = None
        client = make_sequence(status)

        run_once(client, engine, notifier, CALIBRATED_CONFIG, recalibrator=recalibrator)
        recalibrator.reset_mock()
        run_once(client, engine, notifier, CALIBRATED_CONFIG, recalibrator=recalibrator)

        recalibrator.observe.assert_not_called()

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

    def test_successful_shutoff_requires_fresh_confirmation_after_restart(self, mocker, tmp_path):
        import monitor.runner as runner

        extreme = PumpStatus(rpm=1050, power_watts=300, flow_gph=200, is_running=True)
        config = {
            **CALIBRATED_CONFIG,
            "thresholds": {
                **CALIBRATED_CONFIG["thresholds"],
                "consecutive_readings_required": 3,
            },
            "emergency_shutoff": {
                "enabled": True,
                "consecutive_required": 1,
                "delay_seconds": 0,
            },
        }
        client = mocker.MagicMock()
        client.get_status.side_effect = [extreme, extreme, extreme, extreme]
        client.turn_off.return_value = True
        client.set_pump_enabled.return_value = True
        notifier = mocker.MagicMock(spec=NtfyNotifier)
        notifier.send_alert.return_value = True
        engine = Engine(config)
        mocker.patch("monitor.runner.time.sleep")
        mocker.patch.object(runner, "PROJECT_ROOT", tmp_path)
        runner._critical_streak = 0

        for _ in range(3):
            result = run_once(client, engine, notifier, config)

        assert result.level == AlertLevel.CRITICAL
        assert client.turn_off.call_count == 1
        assert list(engine._window) == []
        assert runner._critical_streak == 0

        # The same restarted-pump reading is only the first of a new 3-reading
        # confirmation window, not an immediate second shutoff.
        result = run_once(client, engine, notifier, config)
        assert result.level == AlertLevel.NORMAL
        assert result.pending_elevated
        assert client.turn_off.call_count == 1


def test_trend_check_skips_when_pump_is_off(mocker):
    """An old high-speed session cannot send a forecast while the pump is off."""
    import monitor.runner as runner

    analyzer = mocker.MagicMock()
    notifier = mocker.MagicMock()
    mocker.patch.object(runner.time, "time", return_value=100_000)
    mocker.patch.object(runner, "_last_trend_check", -100_000)

    _check_trend(analyzer, notifier, CALIBRATED_CONFIG, dry_run=False, active_mode="off")

    analyzer.check.assert_not_called()
    notifier.send_info.assert_not_called()


def test_off_poll_does_not_delay_the_next_valid_trend_check(mocker):
    import monitor.runner as runner

    analyzer = mocker.MagicMock()
    analyzer.check.return_value = None
    notifier = mocker.MagicMock()
    mocker.patch.object(runner.time, "time", return_value=100_000)
    mocker.patch.object(runner, "_last_trend_check", -100_000)

    _check_trend(analyzer, notifier, CALIBRATED_CONFIG, dry_run=False, active_mode="off")
    _check_trend(analyzer, notifier, CALIBRATED_CONFIG, dry_run=False, active_mode="low")

    analyzer.check.assert_called_once_with(CALIBRATED_CONFIG, active_mode="low")

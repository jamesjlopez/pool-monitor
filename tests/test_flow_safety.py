"""Emergency flow protection uses real source timestamps and never starts a pump."""

from unittest.mock import Mock
import time

import pytest

from monitor.api_client import _parse_status
from monitor.engine import Engine
from monitor.runner import load_config, run_once
from monitor.types import AlertLevel


def sample(now, flow=50, power=200, age=0):
    fields = {
        key: {"value": str(value), "timestamp": now - age}
        for key, value in {"s3": 1, "s18": power, "s26": flow,
                           "s14": 1, "zp2e2": "Low speed"}.items()
    }
    return {"fields": fields}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    import monitor.runner as runner
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    config = load_config()
    config["flow_safety"] = {"enabled": True, "minimum_flow_gph": 600,
                             "max_sample_age_seconds": 600}
    client, notifier = Mock(), Mock()
    notifier.send_alert.return_value = True
    client.set_pump_enabled.return_value = True
    client.turn_off.return_value = True
    return config, client, notifier, tmp_path


def poll(rig, raw, dry_run=False):
    config, client, notifier, _ = rig
    return run_once(client, Engine(config), notifier, config,
                    status=_parse_status(raw), dry_run=dry_run)


def test_first_low_flow_sample_stops_without_pressure_calibration(rig):
    import time
    result = poll(rig, sample(time.time()))
    assert result.level == AlertLevel.CRITICAL
    rig[1].set_pump_enabled.assert_called_once_with(False)
    rig[1].turn_off.assert_called_once_with()
    rig[2].send_alert.assert_called_once()


@pytest.mark.parametrize("change", ["missing", "invalid", "stale", "future", "off", "no_power", "normal",
                                    "missing_timestamp", "old_power", "nan", "negative"])
def test_invalid_old_or_nonhazardous_data_never_stops(rig, change):
    import time
    raw = sample(time.time())
    if change == "missing":
        del raw["fields"]["s26"]
    elif change == "invalid":
        raw["fields"]["s26"]["value"] = "bad"
    elif change == "stale":
        raw["fields"]["s26"]["timestamp"] -= 601
    elif change == "future":
        raw["fields"]["s26"]["timestamp"] += 60
    elif change == "off":
        raw["fields"]["s3"]["value"] = "0"
    elif change == "no_power":
        raw["fields"]["s18"]["value"] = "0"
    elif change == "missing_timestamp":
        del raw["fields"]["s26"]["timestamp"]
    elif change == "old_power":
        raw["fields"]["s18"]["timestamp"] -= 601
    elif change == "nan":
        raw["fields"]["s26"]["value"] = "NaN"
    elif change == "negative":
        raw["fields"]["s26"]["value"] = "-1"
    else:
        raw["fields"]["s26"]["value"] = "427"
    poll(rig, raw)
    rig[1].set_pump_enabled.assert_not_called()
    rig[1].turn_off.assert_not_called()


def test_dry_run_never_sends_commands_or_notifications(rig):
    import time
    result = poll(rig, sample(time.time()), dry_run=True)
    assert result.level == AlertLevel.CRITICAL
    rig[1].set_pump_enabled.assert_not_called()
    rig[1].turn_off.assert_not_called()
    rig[2].send_alert.assert_not_called()


def test_stop_failure_is_retried_after_process_restart_even_with_old_data(rig):
    import time
    rig[1].set_pump_enabled.return_value = False
    rig[1].turn_off.side_effect = RuntimeError("offline")
    poll(rig, sample(time.time()))
    rig[1].set_pump_enabled.return_value = True
    poll(rig, sample(time.time(), age=7200))
    assert rig[1].set_pump_enabled.call_count == 2
    assert "FAILED" in rig[2].send_alert.call_args_list[0].args[1]


def test_notification_failure_does_not_prevent_stop(rig):
    import time
    rig[2].send_alert.side_effect = RuntimeError("notification offline")
    result = poll(rig, sample(time.time(), flow=0))
    assert result.level == AlertLevel.CRITICAL
    rig[1].set_pump_enabled.assert_called_once_with(False)


def test_pending_stop_retries_even_when_telemetry_fetch_fails(rig):
    config, client, notifier, _ = rig
    client.set_pump_enabled.return_value = False
    poll(rig, sample(time.time()))
    client.get_status.return_value = None
    client.set_pump_enabled.return_value = True
    result = run_once(client, Engine(config), notifier, config)
    assert result.level == AlertLevel.CRITICAL
    assert client.set_pump_enabled.call_count == 2


def test_unknown_program_does_not_hide_extreme_flow_loss(rig):
    import time
    config, client, notifier, _ = rig
    raw = sample(time.time(), flow=0)
    del raw["fields"]["zp2e2"]
    engine = Engine(config)
    result = run_once(client, engine, notifier, config, status=_parse_status(raw))
    assert result.level == AlertLevel.CRITICAL
    client.set_pump_enabled.assert_called_once_with(False)


def test_observed_startup_keeps_bounded_priming_grace(rig):
    import time
    config, client, notifier, _ = rig
    engine = Engine(config)
    engine.mark_pump_start()
    run_once(client, engine, notifier, config, status=_parse_status(sample(time.time())))
    client.set_pump_enabled.assert_not_called()


def test_both_commands_precede_notification_and_success_clears_pending(rig):
    config, client, notifier, root = rig
    calls = Mock()
    calls.attach_mock(client, "client")
    calls.attach_mock(notifier, "notifier")
    poll(rig, sample(time.time()))
    assert [call[0] for call in calls.mock_calls[:3]] == [
        "client.set_pump_enabled", "client.turn_off", "notifier.send_alert"]
    assert not (root / "logs" / "flow-shutoff-pending.json").exists()


def test_disable_exception_still_attempts_program_stop(rig):
    rig[1].set_pump_enabled.side_effect = RuntimeError("network down")
    poll(rig, sample(time.time()))
    rig[1].turn_off.assert_called_once_with()
    assert (rig[3] / "logs" / "flow-shutoff-pending.json").exists()


def test_disabled_guard_does_not_create_stop_request(rig):
    rig[0]["flow_safety"]["enabled"] = False
    poll(rig, sample(time.time()))
    rig[1].set_pump_enabled.assert_not_called()


def test_master_switch_off_overrides_cached_running_measurements(rig):
    raw = sample(time.time())
    raw["fields"]["d25"] = {"value": "0"}
    poll(rig, raw)
    rig[1].set_pump_enabled.assert_not_called()


def test_priming_grace_expires_and_low_flow_then_stops(rig, monkeypatch):
    config, client, notifier, _ = rig
    now = time.time()
    monkeypatch.setattr("monitor.engine.time.time", lambda: now)
    engine = Engine(config)
    engine.mark_pump_start()
    monkeypatch.setattr("monitor.engine.time.time", lambda: now + 121)
    result = run_once(client, engine, notifier, config, status=_parse_status(sample(now + 121)))
    assert result.level == AlertLevel.CRITICAL
    client.set_pump_enabled.assert_called_once_with(False)

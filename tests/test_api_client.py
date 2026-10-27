"""Tests for monitor/api_client.py — MockPentairClient and fixture parsing."""

from pathlib import Path

import pytest

from monitor.api_client import MockPentairClient, _extract, _fixture_to_status, _parse_status
from monitor.types import PumpStatus


class TestPollingBackoff:
    @pytest.fixture
    def client(self, mocker):
        from monitor.api_client import PentairCloudClient
        mocker.patch.object(PentairCloudClient, "_authenticate")
        mocker.patch.object(PentairCloudClient, "_refresh_if_needed")
        client = PentairCloudClient({"pentair": {"email": "test", "password": "test"}})
        client._device_id = "test-device"
        return client

    @pytest.mark.parametrize("header,delay", [(None, 300), ("900", 900), ("bad", 300),
                                             ("0", 300), ("7200", 7200),
                                             ("NaN", 300), ("inf", 300)])
    def test_rate_limit_suppresses_requests_until_deadline(self, client, mocker, header, delay):
        import requests
        response = requests.Response()
        response.status_code = 429
        if header is not None:
            response.headers["Retry-After"] = header
        fetch = mocker.patch.object(client, "_fetch_status", side_effect=requests.HTTPError(response=response))
        clock = mocker.patch("monitor.api_client.time.monotonic", return_value=100)
        assert client.get_status() is None
        clock.return_value = 100 + delay - 1
        assert client.get_status() is None
        assert fetch.call_count == 1
        clock.return_value = 100 + delay
        client.get_status()
        assert fetch.call_count == 2

    def test_http_date_and_repeated_rejections_then_success(self, client, mocker):
        import requests
        from email.utils import formatdate
        response = requests.Response()
        response.status_code = 429
        response.headers["Retry-After"] = formatdate(1900, usegmt=True)
        mocker.patch("monitor.api_client.time.time", return_value=1000)
        clock = mocker.patch("monitor.api_client.time.monotonic", return_value=100)
        fetch = mocker.patch.object(client, "_fetch_status", side_effect=requests.HTTPError(response=response))
        client.get_status()
        assert client._poll_blocked_until == 1000
        response.headers.clear()
        clock.return_value = 1000
        client.get_status()
        assert client._poll_blocked_until == 1600
        clock.return_value = 1600
        fetch.side_effect = None
        fetch.return_value = PumpStatus(0, 0, 0, False)
        assert client.get_status() is not None
        assert client._poll_rejections == 0

    def test_poll_backoff_does_not_block_emergency_disable(self, client, mocker):
        client._poll_blocked_until = float("inf")
        control = mocker.patch.object(client, "_set_control", return_value=True)
        assert client.set_pump_enabled(False)
        control.assert_called_once_with({"d25": "0"})

    def test_repeated_rejections_cap_fallback_at_one_hour(self, client, mocker):
        mocker.patch("monitor.api_client.time.monotonic", return_value=100)
        for _ in range(20):
            client._back_off_polling(None)
        assert client._poll_blocked_until == 3700

    def test_other_http_errors_do_not_claim_rate_limiting(self, client, mocker):
        import requests
        response = requests.Response()
        response.status_code = 500
        mocker.patch.object(client, "_fetch_status", side_effect=requests.HTTPError(response=response))
        assert client.get_status() is None
        assert client._poll_blocked_until == 0

FIXTURES = Path(__file__).parent / "fixtures"


class TestMockClient:
    def test_returns_status_from_fixture_file(self):
        client = MockPentairClient(fixture_path=FIXTURES / "pump_low_clean.json")
        status = client.get_status()
        assert isinstance(status, PumpStatus)
        assert status.is_running is True
        assert status.rpm == 1050

    def test_pump_off_fixture(self):
        client = MockPentairClient(fixture_path=FIXTURES / "pump_off.json")
        status = client.get_status()
        assert status.is_running is False
        assert status.rpm == 0

    def test_sequence_loops(self):
        from monitor.types import PumpStatus
        s1 = PumpStatus(rpm=1050, power_watts=148, flow_gph=1820, is_running=True)
        s2 = PumpStatus(rpm=2800, power_watts=595, flow_gph=4180, is_running=True)
        client = MockPentairClient(sequence=[s1, s2])
        assert client.get_status().rpm == 1050
        assert client.get_status().rpm == 2800
        assert client.get_status().rpm == 1050  # loops

    def test_empty_sequence_returns_none(self):
        client = MockPentairClient()
        assert client.get_status() is None

    def test_set_speed_returns_true(self):
        client = MockPentairClient(fixture_path=FIXTURES / "pump_low_clean.json")
        assert client.set_speed_program(2) is True

    def test_turn_off_returns_true(self):
        client = MockPentairClient(fixture_path=FIXTURES / "pump_low_clean.json")
        assert client.turn_off() is True


class TestFixtureParsing:
    def test_cloud_status_preserves_source_telemetry_version(self):
        status = _parse_status({
            "timestamp": "device-update",
            "fields": {
                "s3": {"value": "1"}, "s14": {"value": "0"},
                "s17": {"value": "1050", "timestamp": "rpm-update"},
                "s18": {"value": "148", "timestamp": "watts-update"},
                "s26": {"value": "303", "timestamp": "flow-update"},
            },
        })

        assert status.telemetry_version == "device-update|rpm-update|watts-update|flow-update"

    def test_cloud_status_preserves_active_program_context(self):
        status = _parse_status({
            "fields": {
                "s3": {"value": "1"}, "s14": {"value": "1"},
                "s15": {"value": "3"}, "s16": {"value": "705"},
                "s17": {"value": "1050"}, "s18": {"value": "148"},
                "s19": {"value": "705"}, "s26": {"value": "303"},
                "zp2e2": {"value": "Low speed"},
            },
        })

        assert status.raw["prog_name"] == "low speed"
        assert status.raw["active_reference"] == "3"
        assert status.raw["active_setpoint"] == 705.0
        assert status.pressure_psi == 10.5
        assert status.motor_speed_pct == 70.5

    def test_cloud_status_without_a_program_never_infers_mode_from_pressure(self):
        status = _parse_status({
            "fields": {
                "s3": {"value": "1"}, "s14": {"value": "0"},
                "s17": {"value": "1050"}, "s18": {"value": "148"},
                "s26": {"value": "303"},
            },
        })

        assert status.pressure_raw == 1050
        assert status.speed_mode == "unknown"

    def test_low_clean_speed_mode(self):
        client = MockPentairClient(fixture_path=FIXTURES / "pump_low_clean.json")
        status = client.get_status()
        assert status.speed_mode == "low"

    def test_high_clean_speed_mode(self):
        client = MockPentairClient(fixture_path=FIXTURES / "pump_high_clean.json")
        status = client.get_status()
        assert status.speed_mode == "high"

    def test_clogged_fixture_has_high_ratio(self):
        client = MockPentairClient(fixture_path=FIXTURES / "pump_low_clogged.json")
        status = client.get_status()
        assert status.watts_per_gph is not None
        # Clogged ratio should be significantly above clean baseline (0.083)
        assert status.watts_per_gph > 0.12

    def test_watts_per_gph_zero_flow_is_none(self):
        from monitor.types import PumpStatus
        s = PumpStatus(rpm=1050, power_watts=200, flow_gph=0, is_running=True)
        assert s.watts_per_gph is None


class TestExtractHelper:
    def test_finds_first_matching_key(self):
        data = {"rpm": 1050, "watts": 150}
        assert _extract(data, ["rpm", "speed"]) == 1050

    def test_falls_through_to_second_key(self):
        data = {"speed": 1050}
        assert _extract(data, ["rpm", "speed"]) == 1050

    def test_case_insensitive(self):
        data = {"RPM": 1050}
        assert _extract(data, ["rpm"]) == 1050

    def test_recurses_into_nested_dict(self):
        data = {"telemetry": {"rpm": 2800}}
        assert _extract(data, ["rpm"]) == 2800

    def test_returns_default_when_not_found(self):
        assert _extract({}, ["rpm", "speed"], default=0) == 0

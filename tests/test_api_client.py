"""Tests for monitor/api_client.py — MockPentairClient and fixture parsing."""

from pathlib import Path

import pytest

from monitor.api_client import MockPentairClient, _extract, _fixture_to_status
from monitor.types import PumpStatus

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

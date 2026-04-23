"""Tests for monitor/engine.py — speed-aware anomaly detection."""

import time

import pytest

from monitor.engine import Engine
from monitor.types import AlertLevel, PumpStatus


# Calibrated config: baseline ratios set so we can exercise threshold logic
CALIBRATED_CONFIG = {
    "thresholds": {
        "startup_grace_seconds": 120,
        "consecutive_readings_required": 3,
        "low_speed": {
            "alert_psi": 12,
            "emergency_psi": 18,
            "baseline_watts_per_gph": 0.083,  # ~150W / 1800 GPH
            "alert_ratio_pct": 30,
            "emergency_ratio_pct": 80,
        },
        "high_speed": {
            "alert_psi": 20,
            "emergency_psi": 30,
            "baseline_watts_per_gph": 0.143,  # ~600W / 4200 GPH
            "alert_ratio_pct": 30,
            "emergency_ratio_pct": 80,
        },
        "alert_cooldown_minutes": 30,
    }
}

# Uncalibrated config: baseline_watts_per_gph = null → uses flow heuristics
UNCALIBRATED_CONFIG = {
    "thresholds": {
        "startup_grace_seconds": 120,
        "consecutive_readings_required": 3,
        "low_speed": {
            "alert_psi": 12,
            "emergency_psi": 18,
            "baseline_watts_per_gph": None,
            "alert_ratio_pct": 30,
            "emergency_ratio_pct": 80,
        },
        "high_speed": {
            "alert_psi": 20,
            "emergency_psi": 30,
            "baseline_watts_per_gph": None,
            "alert_ratio_pct": 30,
            "emergency_ratio_pct": 80,
        },
        "alert_cooldown_minutes": 30,
    }
}


def make_status(rpm=1050, watts=148.0, gph=1820.0, running=True) -> PumpStatus:
    return PumpStatus(rpm=rpm, power_watts=watts, flow_gph=gph, is_running=running)


def feed_n(engine, status, n):
    """Feed the same status n times to fill the rolling window."""
    results = [engine.process(status) for _ in range(n)]
    return results


class TestSpeedModeDerivation:
    def test_low_speed_mode(self):
        s = make_status(rpm=1050)
        assert s.speed_mode == "low"

    def test_high_speed_mode(self):
        s = make_status(rpm=2800)
        assert s.speed_mode == "high"

    def test_off_mode_when_not_running(self):
        s = make_status(rpm=0, running=False)
        assert s.speed_mode == "off"

    def test_rpm_boundary_1499_is_low(self):
        assert make_status(rpm=1499).speed_mode == "low"

    def test_rpm_boundary_1500_is_high(self):
        assert make_status(rpm=1500).speed_mode == "high"


class TestNormalOperation:
    def test_normal_low_speed_clean_filter(self):
        engine = Engine(CALIBRATED_CONFIG)
        # Normal: ratio = 148/1820 = 0.081 ≈ baseline 0.083 (within 30%)
        results = feed_n(engine, make_status(rpm=1050, watts=148, gph=1820), 3)
        assert results[-1].level == AlertLevel.NORMAL

    def test_normal_high_speed_clean_filter(self):
        engine = Engine(CALIBRATED_CONFIG)
        results = feed_n(engine, make_status(rpm=2800, watts=595, gph=4180), 3)
        assert results[-1].level == AlertLevel.NORMAL

    def test_pump_off_returns_normal(self):
        engine = Engine(CALIBRATED_CONFIG)
        result = engine.process(make_status(rpm=0, watts=0, gph=0, running=False))
        assert result.level == AlertLevel.NORMAL
        assert result.speed_mode == "off"


class TestWarnThreshold:
    def test_warn_fires_after_3_consecutive_readings(self):
        engine = Engine(CALIBRATED_CONFIG)
        # ratio = 110/1050 = 0.1048, baseline = 0.083, deviation = +26%... too low.
        # Use ratio that's 40% above baseline (0.083 * 1.40 = 0.116) → WARN not CRITICAL:
        # watts=121, gph=1042 → ratio = 0.116, deviation ~40% — above 30% alert, below 80% emergency
        mild_clog = make_status(rpm=1050, watts=121, gph=1042)
        results = feed_n(engine, mild_clog, 3)
        assert results[-1].level == AlertLevel.WARN

    def test_warn_suppressed_with_only_2_readings(self):
        engine = Engine(CALIBRATED_CONFIG)
        clogged = make_status(rpm=1050, watts=195, gph=1100)
        results = feed_n(engine, clogged, 2)
        assert results[-1].level == AlertLevel.NORMAL  # not enough data yet

    def test_warn_resets_after_normal_reading(self):
        engine = Engine(CALIBRATED_CONFIG)
        clogged = make_status(rpm=1050, watts=195, gph=1100)
        clean = make_status(rpm=1050, watts=148, gph=1820)
        feed_n(engine, clogged, 2)
        result = engine.process(clean)
        assert result.level == AlertLevel.NORMAL


class TestCriticalThreshold:
    def test_critical_fires_on_extreme_clogging(self):
        engine = Engine(CALIBRATED_CONFIG)
        # ratio = 195/500 = 0.390, baseline = 0.083, deviation = +370% → above 80% emergency
        extreme = make_status(rpm=1050, watts=195, gph=500)
        results = feed_n(engine, extreme, 3)
        assert results[-1].level == AlertLevel.CRITICAL

    def test_high_speed_critical(self):
        engine = Engine(CALIBRATED_CONFIG)
        # ratio = 780/2100 = 0.371, baseline = 0.143, deviation = +160% → above 80%
        extreme = make_status(rpm=2800, watts=780, gph=2100)
        results = feed_n(engine, extreme, 3)
        assert results[-1].level == AlertLevel.CRITICAL


class TestGracePeriod:
    def test_no_alert_during_startup_grace(self):
        engine = Engine(CALIBRATED_CONFIG)
        engine.mark_pump_start()
        # Startup priming — high power, low flow — would normally alert
        startup = make_status(rpm=3000, watts=650, gph=1800)
        result = engine.process(startup)
        assert result.level == AlertLevel.NORMAL
        assert "grace" in result.reason.lower()

    def test_alert_fires_after_grace_expires(self):
        engine = Engine({
            "thresholds": {
                **CALIBRATED_CONFIG["thresholds"],
                "startup_grace_seconds": 0,  # zero-length grace for testing
                "consecutive_readings_required": 1,
            }
        })
        engine.mark_pump_start()
        clogged = make_status(rpm=1050, watts=195, gph=500)
        result = engine.process(clogged)
        assert result.level != AlertLevel.NORMAL

    def test_window_clears_on_pump_start(self):
        engine = Engine(CALIBRATED_CONFIG)
        clogged = make_status(rpm=1050, watts=195, gph=1100)
        feed_n(engine, clogged, 3)  # fill window with warn readings
        engine.mark_pump_start()    # restart clears window
        # Grace period active — everything should be NORMAL
        result = engine.process(clogged)
        assert result.level == AlertLevel.NORMAL


class TestUncalibratedMode:
    def test_extreme_low_flow_triggers_warn(self):
        engine = Engine(UNCALIBRATED_CONFIG)
        # Very low flow with reasonable watts — heuristic should fire at least WARN
        # (may be CRITICAL since engine falls back to default baselines)
        blocked = make_status(rpm=1050, watts=250, gph=500)
        results = feed_n(engine, blocked, 3)
        assert results[-1].level >= AlertLevel.WARN

    def test_normal_flow_no_alert(self):
        engine = Engine(UNCALIBRATED_CONFIG)
        normal = make_status(rpm=1050, watts=148, gph=1820)
        results = feed_n(engine, normal, 3)
        assert results[-1].level == AlertLevel.NORMAL

    def test_zero_flow_triggers_warn(self):
        engine = Engine(UNCALIBRATED_CONFIG)
        blocked = make_status(rpm=1050, watts=200, gph=0)
        result = engine.process(blocked)
        assert result.level == AlertLevel.WARN


class TestRollingWindow:
    def test_mixed_readings_do_not_alert(self):
        engine = Engine(CALIBRATED_CONFIG)
        clogged = make_status(rpm=1050, watts=195, gph=1100)
        clean = make_status(rpm=1050, watts=148, gph=1820)
        engine.process(clogged)
        engine.process(clean)
        result = engine.process(clogged)
        assert result.level == AlertLevel.NORMAL  # not all 3 are warn

    def test_warn_does_not_escalate_to_critical(self):
        engine = Engine(CALIBRATED_CONFIG)
        # ratio just above alert threshold, below emergency
        mild_clog = make_status(rpm=1050, watts=160, gph=1200)  # ratio ~0.133, +60% above 0.083
        results = feed_n(engine, mild_clog, 3)
        assert results[-1].level == AlertLevel.WARN
        assert results[-1].level != AlertLevel.CRITICAL

"""Tests for filter cleaning auto-recalibration."""

import textwrap

from monitor.recalibrator import Recalibrator
from monitor.types import PumpStatus


def make_config(low=0.158, high=0.1929):
    return {
        "thresholds": {
            "low_speed": {"baseline_watts_per_gph": low},
            "high_speed": {"baseline_watts_per_gph": high},
        }
    }


def write_config(path, low=0.158, high=0.1929):
    path.write_text(textwrap.dedent(f"""\
        thresholds:
          low_speed:
            baseline_watts_per_gph: {low}
          high_speed:
            baseline_watts_per_gph: {high}
        """))


def high_status(rpm, watts, gph):
    return PumpStatus(
        rpm=rpm,
        power_watts=watts,
        flow_gph=gph,
        is_running=True,
        speed_mode="high",
    )


def test_june_6_hose_drain_profile_does_not_recalibrate(tmp_path):
    config_path = tmp_path / "config.yaml"
    log_path = tmp_path / "recalibrations.json"
    write_config(config_path)
    config = make_config()
    recalibrator = Recalibrator(config_path, log_path)

    dirty = high_status(1982, 656, 1638)  # ratio 0.4005, elevated history
    for _ in range(3):
        assert recalibrator.observe(dirty, config) is None

    hose_drain = high_status(1024, 62, 3510)  # June 6 drain/bypass-like profile
    assert recalibrator.observe(hose_drain, config) is None
    assert recalibrator.observe(high_status(1619, 765, 3804), config) is None
    assert recalibrator.observe(high_status(1654, 762, 3702), config) is None

    assert config["thresholds"]["high_speed"]["baseline_watts_per_gph"] == 0.1929
    assert "0.1929" in config_path.read_text()
    assert not log_path.exists()


def test_stable_clean_landing_recalibrates_after_dirty_history(tmp_path):
    config_path = tmp_path / "config.yaml"
    log_path = tmp_path / "recalibrations.json"
    write_config(config_path)
    config = make_config()
    recalibrator = Recalibrator(config_path, log_path)

    dirty = high_status(1982, 656, 1638)
    for _ in range(3):
        assert recalibrator.observe(dirty, config) is None

    clean = [
        high_status(1960, 720, 4000),  # 0.1800
        high_status(1960, 724, 4000),  # 0.1810
        high_status(1960, 728, 4000),  # 0.1820
    ]
    event = None
    for status in clean:
        event = recalibrator.observe(status, config)

    assert event is not None
    assert event.speed_mode == "high"
    assert event.new_baseline == 0.181
    assert config["thresholds"]["high_speed"]["baseline_watts_per_gph"] == 0.181

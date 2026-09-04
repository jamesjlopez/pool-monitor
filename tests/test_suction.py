from monitor.suction import SuctionRestrictionDetector
from monitor.types import PumpStatus


def status(flow, pressure):
    return PumpStatus(rpm=0, power_watts=500, flow_gph=flow, is_running=True,
                      pressure_psi=pressure, speed_mode="low",
                      raw={"prog_name": "low speed", "active_reference": "3", "active_setpoint": 705})


def test_sudden_same_program_drop_warns_once():
    detector = SuctionRestrictionDetector()
    assert detector.observe(status(3400, 10.4)) is None
    warning = detector.observe(status(2600, 11.1))
    assert warning.kind == "sudden"
    assert "skimmer basket" in warning.message
    assert detector.observe(status(2400, 11.4)) is None


def test_small_change_does_not_warn():
    detector = SuctionRestrictionDetector()
    detector.observe(status(3400, 10.4))
    assert detector.observe(status(3200, 10.7)) is None

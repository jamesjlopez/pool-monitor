"""Independent flow evidence and persisted notification delivery."""
import csv
from unittest.mock import Mock

import pytest

from monitor.return_flow import check_return_flow, evaluate_flow


def row(stamp, flow=3500, program='low speed', setpoint=705):
    return dict(timestamp='2026-09-24T10:00:00', telemetry_version=f'{stamp}|{stamp}|{stamp}|{stamp}',
                active_program=program, active_reference='3', active_setpoint=str(float(setpoint)),
                flow_gph=str(float(flow)), power_watts='500.0', pressure_psi='10.0')


def history(loss=30):
    return [row(i * 3600) for i in range(1, 8)] + [row(8 * 3600, 3500*(1-loss/100)), row(9 * 3600, 3500*(1-loss/100))]


@pytest.mark.parametrize('loss,level', [(0,0),(15,1),(25,2),(40,3)])
def test_thresholds_use_independent_confirmations(loss, level):
    result=evaluate_flow(history(loss), {}, 9*3600+30)
    assert result['level']==level
    assert result['reference']==3500


def test_duplicates_do_not_confirm_and_partial_update_is_ignored():
    rows=history()[:-1]
    assert evaluate_flow(rows+[rows[-1]]*5, {}, 8*3600+30)['level']==0
    mixed={**rows[-1], 'telemetry_version':f'30000|30000|30000|{8*3600}'}
    assert evaluate_flow(rows+[mixed], {}, 30030) is None


def test_other_programs_do_not_reset_or_confirm_flow_loss():
    rows=history()[:-1]+[row(8*3600+1800, 1000, 'high speed', 854)]+history()[-1:]
    assert evaluate_flow(rows, {}, 9*3600+30)['level']==2
    rows[-1]['active_setpoint']='706.0'
    assert evaluate_flow(rows, {}, 9*3600+30) is None


def test_expired_future_and_three_day_gap():
    rows=history()
    assert evaluate_flow(rows, {}, 9*3600+5400) is None
    assert evaluate_flow(rows, {}, 9*3600-1) is None
    stamp=9*3600+72*3600
    rows[-1]=row(stamp, 2400)
    assert evaluate_flow(rows, {}, stamp+30)['level']==0


def write_rows(path, rows):
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=rows[0].keys())
        writer.writeheader(); writer.writerows(rows)


def test_delivery_failure_retries_and_success_survives_restart(tmp_path):
    metrics=tmp_path/'metrics.csv'; state=tmp_path/'state.json'
    write_rows(metrics,history())
    notifier=Mock(); record=Mock()
    notifier.send_alert.side_effect=[False,True]
    check_return_flow(metrics,state,{},notifier,record,9*3600+30)
    assert not state.exists()
    check_return_flow(metrics,state,{},notifier,record,9*3600+60)
    check_return_flow(metrics,state,{},notifier,record,9*3600+90)
    assert notifier.send_alert.call_count==2
    assert record.call_count==2
    assert record.call_args.args[-1] is True


def test_escalation_recovery_and_reminder(tmp_path):
    metrics=tmp_path/'metrics.csv'; state=tmp_path/'state.json'
    rows=history(15); notifier=Mock(); notifier.send_alert.return_value=True; record=Mock()
    write_rows(metrics,rows)
    check_return_flow(metrics,state,{},notifier,record,9*3600+30)
    rows.extend([row(10*3600,2000),row(11*3600,2000)])
    write_rows(metrics,rows)
    check_return_flow(metrics,state,{},notifier,record,11*3600+30)
    assert notifier.send_alert.call_count==2
    rows.extend([row(22*3600,2000),row(23*3600,2000)])
    write_rows(metrics,rows)
    check_return_flow(metrics,state,{},notifier,record,23*3600+31)
    assert notifier.send_alert.call_count==3
    rows.append(row(24*3600)); write_rows(metrics,rows)
    check_return_flow(metrics,state,{},notifier,record,24*3600+30)
    rows.extend([row(25*3600,2000),row(26*3600,2000)]); write_rows(metrics,rows)
    check_return_flow(metrics,state,{},notifier,record,26*3600+30)
    assert notifier.send_alert.call_count==4


def test_run_once_checks_logged_flow_and_dry_run_does_not_send(tmp_path, mocker):
    from monitor import runner
    from monitor.data_logger import DataLogger
    from monitor.engine import Engine
    from monitor.types import PumpStatus
    config={'thresholds':{'low_speed':{},'high_speed':{}}}
    mocker.patch.object(runner,'PROJECT_ROOT',tmp_path)
    check=mocker.patch.object(runner,'check_return_flow')
    s=PumpStatus(rpm=1000,power_watts=500,flow_gph=2400,is_running=True,
                 pressure_psi=10,raw={'prog_name':'low speed','active_reference':'3','active_setpoint':705})
    logger=DataLogger(tmp_path/'metrics.csv')
    runner.run_once(Mock(),Engine(config),Mock(),config,status=s,data_logger=logger)
    check.assert_called_once()
    check.reset_mock()
    runner.run_once(Mock(),Engine(config),Mock(),config,status=s,data_logger=logger,dry_run=True)
    check.assert_not_called()

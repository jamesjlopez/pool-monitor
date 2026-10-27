"""Return-flow advisories from independent, same-program hydraulic samples."""

import csv
import json
import math
import time
from pathlib import Path

from .hydraulic_quality import classify_hydraulic_rows
from .types import AlertLevel


def evaluate_flow(rows: list[dict], config: dict, now: float) -> dict | None:
    """Match dashboard p90 references; repeated or old samples cannot confirm loss."""
    verified = []
    for row, audit in zip(rows, classify_hydraulic_rows(rows)):
        if audit['hydraulic_quality'] != 'verified':
            continue
        try:
            parts = row['telemetry_version'].split('|')
            source = min(int(parts[1]), int(parts[3]))
            setpoint = float(row['active_setpoint'])
            flow = float(row['flow_gph'])
            watts = float(row['power_watts'])
            key = (row['active_program'], row['active_reference'], setpoint)
            if not all(math.isfinite(v) for v in (setpoint, flow, watts)):
                continue
            if not key[0] or not key[1] or flow <= 0 or watts <= 0:
                continue
            verified.append((key, source, flow, row))
        except (KeyError, ValueError, IndexError):
            continue
    if not verified or not rows:
        return None
    key, source, flow, latest = verified[-1]
    # A partial update or program change must not reuse an older verified pair.
    last = rows[-1]
    for field in ('active_program', 'active_reference', 'active_setpoint', 'flow_gph', 'pressure_psi'):
        if last.get(field) != latest.get(field):
            return None
    last_parts = last.get('telemetry_version', '').split('|')
    parts = latest['telemetry_version'].split('|')
    if len(last_parts) != 4 or (last_parts[1], last_parts[3]) != (parts[1], parts[3]):
        return None
    expiry = config.get('telemetry_health', {}).get('stale_alert_after_seconds', 5400)
    if not 0 <= now - source < expiry:
        return None
    samples = [r for r in verified if r[0] == key]
    if len(samples) < 5:
        return None
    values = sorted(r[2] for r in samples)
    reference = values[math.floor((len(values) - 1) * .9)]
    cfg = config.get('dashboard_return_flow', {})
    thresholds = [cfg.get('watch_loss_pct', 15), cfg.get('clean_loss_pct', 25), cfg.get('inspect_loss_pct', 40)]
    required = cfg.get('consecutive_readings_required', 2)
    def level(value):
        loss = max(0, (1 - value / reference) * 100)
        return sum(loss + 1e-9 >= threshold for threshold in thresholds)
    recent = []
    newer = None
    for _, stamp, value, _ in reversed(samples):
        if newer is not None and newer - stamp >= 72 * 3600:
            break
        recent.append(level(value))
        newer = stamp
        if len(recent) == required:
            break
    confirmed = min(recent) if len(recent) == required else 0
    return {'key': json.dumps(key), 'source': source, 'level': confirmed,
            'raw_level': level(flow), 'flow': flow, 'reference': reference,
            'loss': max(0, (1 - flow / reference) * 100), 'program': key[0]}


def check_return_flow(metrics_path: Path, state_path: Path, config: dict, notifier,
                      record_notification, now: float | None = None) -> dict | None:
    """Persist successful delivery per program; retry failures and notify escalation."""
    now = time.time() if now is None else now
    with metrics_path.open(newline='') as source:
        result = evaluate_flow(list(csv.DictReader(source)), config, now)
    if result is None:
        return None
    try:
        state = json.loads(state_path.read_text())
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    key = result['key']
    previous = state.get(key, {})
    if not isinstance(previous, dict):
        previous = {}
    if result['raw_level'] == 0:
        state[key] = {'level': 0, 'sent_at': 0}
    elif result['level'] > 0:
        repeat = config.get('dashboard_return_flow', {}).get('reminder_hours', 12) * 3600
        if result['level'] <= previous.get('level', 0) and now - previous.get('sent_at', 0) < repeat:
            return result
        label = {1: 'Watch return flow', 2: 'Check for a flow restriction', 3: 'Inspect reduced return flow now'}[result['level']]
        reason = (f"{label}: {result['loss']:.0f}% below the recent same-program reference "
                  f"[{result['program']}], confirmed by independent readings. "
                  'Check skimmer and pump baskets, water level, and other restrictions; the cause is not identified.')
        summary = f"Return flow: {result['flow']:.0f} GPH | Reference: {result['reference']:.0f} GPH"
        sent = notifier.send_alert(AlertLevel.WARN, reason, summary)
        record_notification(AlertLevel.WARN, reason, summary, sent)
        if not sent:
            return result
        state[key] = {'level': result['level'], 'sent_at': now}
    else:
        return result
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state))
    temporary.replace(state_path)
    return result

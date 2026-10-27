"""Conservative low-flow shutdown, independent of uncalibrated pressure.

This is cloud-based backup protection, not a replacement for onboard dry-run
and loss-of-prime protection. A new sample may already be several minutes old.
"""

import json
import logging
import math
import time
from datetime import datetime
from pathlib import Path

from .types import AlertLevel, EngineResult, PumpStatus

log = logging.getLogger(__name__)


def low_flow_reason(status: PumpStatus | None, config: dict) -> str | None:
    """Require explicit valid flow and power, with recent source timestamps."""
    cfg = config.get("flow_safety", {})
    if status is None or not cfg.get("enabled", False) or not status.is_running:
        return None
    snapshot = status.raw.get("fields_snapshot", {})
    if any(str(snapshot.get(key)) == "0" for key in ("d25", "appuse")):
        return None
    timestamps = status.raw.get("field_timestamps", {})
    try:
        flow = float(snapshot["s26"]) * 6  # tenths GPM to GPH
        power = float(snapshot["s18"])
        sources = [float(timestamps[key]) for key in ("s18", "s26")]
        maximum_age = float(cfg.get("max_sample_age_seconds", 600))
        minimum_flow = float(cfg.get("minimum_flow_gph", 600))
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in [flow, power, *sources, maximum_age, minimum_flow]):
        return None
    now = time.time()
    if any(not 0 <= now - ts <= maximum_age for ts in sources):
        return None
    if power <= 0 or not 0 <= flow <= minimum_flow:
        return None
    return (f"Possible water starvation / loss of prime: powered pump ({power:.0f} W) "
            f"reports only {flow:.0f} GPH (emergency limit {minimum_flow:.0f} GPH). "
            "Check water level, skimmer, pump basket and suction plumbing.")


def protect_flow(status, client, notifier, config, logs: Path, *, dry_run=False,
                 startup_grace=False) -> EngineResult | None:
    """Stop before notifications or logging can delay commands; retry failed stops.

    Persist an unresolved stop across process restarts. Once the master disable
    command is accepted, manual re-enabling in the Pentair app is required.
    Command acceptance does not prove that the motor physically stopped.
    """
    pending = logs / "flow-shutoff-pending.json"
    reason = None
    if pending.exists():
        # Even a damaged pending file must not silently cancel a requested stop.
        reason = "Retrying an unresolved emergency low-flow stop."
        try:
            saved_reason = json.loads(pending.read_text())["reason"]
            if isinstance(saved_reason, str) and saved_reason:
                reason = saved_reason
        except (OSError, ValueError, KeyError, TypeError):
            log.exception("Cannot read pending low-flow stop; retaining stop request")
    if reason is None and not startup_grace:
        reason = low_flow_reason(status, config)
    if reason is None:
        return None
    result = EngineResult(AlertLevel.CRITICAL, reason, speed_mode=status.speed_mode if status else "unknown",
                          consecutive_count=1)
    if dry_run:
        log.warning("[DRY RUN] Would stop pump immediately: %s", reason)
        return result

    try:
        logs.mkdir(parents=True, exist_ok=True)
        temp = pending.with_suffix(".tmp")
        temp.write_text(json.dumps({"reason": reason, "requested_at": time.time()}))
        temp.replace(pending)
    except OSError:
        log.exception("Could not persist stop request; still attempting emergency stop")

    # Always attempt both commands independently, even if the first throws.
    disabled = stopped = False
    try:
        disabled = client.set_pump_enabled(False) is True
    except Exception:
        log.exception("Emergency master disable failed")
    try:
        stopped = client.turn_off() is True
    except Exception:
        log.exception("Emergency program stop failed")

    outcome = (
        "Emergency OFF command accepted; scheduled restarts disabled. "
        "Verify the pump is stopped. Re-enable manually only after restoring water supply."
        if disabled else
        "SHUTOFF FAILED or schedule disable unconfirmed — turn off manually immediately. "
        "The monitor will retry."
    )
    log.error("%s %s", reason, outcome)
    try:
        with (logs / "shutoff.log").open("a") as audit:
            audit.write(json.dumps({"ts": time.time(), "cause": "low_flow", "reason": reason,
                                    "disable_accepted": disabled, "stop_accepted": stopped}) + "\n")
        if disabled:
            pending.unlink(missing_ok=True)
    except OSError:
        log.exception("Could not finish emergency stop audit; pending stop may be retried")
    try:
        sent = notifier.send_alert(AlertLevel.CRITICAL, f"{reason}\n{outcome}",
                                   (f"Power: {status.power_watts:.0f} W | Flow: {status.flow_gph:.0f} GPH"
                                    if status else "Current pump telemetry unavailable"))
        # Keep the outcome available to the dashboard without coupling to runner.
        path = logs / "notifications.json"
        records = json.loads(path.read_text()) if path.exists() else []
        records.append({"ts": datetime.now().isoformat(timespec="seconds"), "level": "critical",
                        "reason": f"{reason}\n{outcome}", "summary": "Emergency low-flow stop",
                        "sent": bool(sent)})
        path.write_text(json.dumps(records[-100:], indent=2))
    except Exception:
        log.exception("Emergency notification or notification logging failed")
    return result

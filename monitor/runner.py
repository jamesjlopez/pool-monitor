#!/usr/bin/env python3
"""
Pool Monitor Runner — main entry point.

Usage:
    python -m monitor.runner                  # continuous loop (reads config.yaml)
    python -m monitor.runner --once           # single poll cycle then exit
    python -m monitor.runner --once --dry-run # poll but don't send notifications
    python -m monitor.runner --test-notify    # send test ntfy notification and exit
    python -m monitor.runner --config /path/to/config.yaml

The core run_once() function is kept separate from the loop so tests can call it
with injected dependencies (no real pump or ntfy required).
"""

import argparse
import json
import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path
from typing import Optional


def _load_dotenv(path: Path):
    """Load a .env file into os.environ without requiring python-dotenv."""
    if not path.exists():
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            # Only strip quotes if they symmetrically wrap the value
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            if key and key not in os.environ:
                os.environ[key] = val


# Auto-load .env from project root (silently, so creds don't need to be in the shell)
_load_dotenv(Path(__file__).parent.parent / ".env")

import yaml

from .api_client import MockPentairClient, PentairCloudClient

from .data_logger import DataLogger
from .engine import Engine
from .notifier import NtfyNotifier
from .types import AlertLevel, EngineResult, PumpStatus

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_CONFIG    = PROJECT_ROOT / "config.yaml"
STATE_FILE        = PROJECT_ROOT / "logs" / "state.json"
ERRORS_FILE       = PROJECT_ROOT / "logs" / "errors.json"
NOTIFICATIONS_FILE = PROJECT_ROOT / "logs" / "notifications.json"
MAX_ERRORS         = 10
MAX_NOTIFICATIONS  = 100


def _record_error(message: str) -> None:
    """Append an error entry to errors.json, keeping the last MAX_ERRORS entries."""
    import datetime as _dt
    entry = {"ts": _dt.datetime.now().isoformat(timespec="seconds"), "message": message}
    try:
        existing = json.loads(ERRORS_FILE.read_text()) if ERRORS_FILE.exists() else []
    except (json.JSONDecodeError, OSError):
        existing = []
    existing.append(entry)
    ERRORS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ERRORS_FILE.write_text(json.dumps(existing[-MAX_ERRORS:]))


def _record_notification(level: "AlertLevel", reason: str, summary: str, sent: bool) -> None:
    """Append a notification event to notifications.json, keeping the last MAX_NOTIFICATIONS entries."""
    import datetime as _dt
    entry = {
        "ts": _dt.datetime.now().isoformat(timespec="seconds"),
        "level": level.name.lower(),
        "reason": reason,
        "summary": summary,
        "sent": sent,
    }
    try:
        existing = json.loads(NOTIFICATIONS_FILE.read_text()) if NOTIFICATIONS_FILE.exists() else []
    except (json.JSONDecodeError, OSError):
        existing = []
    existing.append(entry)
    NOTIFICATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    NOTIFICATIONS_FILE.write_text(json.dumps(existing[-MAX_NOTIFICATIONS:], indent=2))


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def setup_logging(config: dict):
    level = getattr(logging, config.get("logging", {}).get("level", "INFO"), logging.INFO)
    log_file = config.get("logging", {}).get("file")

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        log_path = PROJECT_ROOT / log_file
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_path, maxBytes=5 * 1024 * 1024, backupCount=3
            )
        )

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        handlers=handlers,
    )


log = logging.getLogger(__name__)

# When a reading is elevated, poll this many more times at short intervals
# to confirm before alerting — catches transients (priming, startup spikes).
FAST_CONFIRM_INTERVAL = 120  # seconds between confirmation polls

# Track consecutive CRITICAL readings for emergency shutoff gate
_critical_streak = 0
_shutoff_required = 1   # overridden by config at runtime


def _load_state(engine: "Engine", notifier: "NtfyNotifier") -> None:
    """Restore rolling window and cooldown timers from disk (survives cron restarts)."""
    global _critical_streak
    try:
        state = json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return
    if "window" in state:
        from .types import AlertLevel
        levels = [AlertLevel[l.upper()] for l in state["window"] if l.upper() in AlertLevel.__members__]
        engine.seed_window(levels)
    if "notifier_last_sent" in state:
        from .types import AlertLevel
        notifier._last_sent = {
            AlertLevel(int(k)): v for k, v in state["notifier_last_sent"].items()
        }
    _critical_streak = state.get("critical_streak", 0)
    engine._zero_flow_streak = state.get("zero_flow_streak", 0)


def _save_state(engine: "Engine", notifier: "NtfyNotifier") -> None:
    """Persist rolling window and cooldown timers to disk."""
    state = {
        "window": [r.level.name.lower() for r in engine._window],
        "notifier_last_sent": {str(k.value): v for k, v in notifier._last_sent.items()},
        "critical_streak": _critical_streak,
        "zero_flow_streak": engine._zero_flow_streak,
    }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state))


def run_once(
    client,
    engine: Engine,
    notifier: NtfyNotifier,
    config: dict,
    dry_run: bool = False,
    data_logger: Optional[DataLogger] = None,
) -> Optional[EngineResult]:
    """
    Single poll cycle. Fetch pump status, evaluate it, send alert if needed.
    This function is the core testable unit — all dependencies are injected.
    Returns EngineResult, or None if the pump could not be reached.
    """
    global _critical_streak, _shutoff_required

    _shutoff_required = (
        config.get("emergency_shutoff", {}).get("consecutive_required", 5)
    )

    status = client.get_status()
    if status is None:
        msg = "Could not get pump status — API unreachable or auth failure"
        log.warning(msg)
        if not dry_run:
            _record_error(msg)
        return None

    result = engine.process(status)
    _log_result(result, status)
    if data_logger is not None:
        data_logger.log(status, result)

    # Emergency shutoff streak tracking
    if result.level == AlertLevel.CRITICAL:
        _critical_streak += 1
    else:
        _critical_streak = 0

    if result.level > AlertLevel.NORMAL:
        summary = _status_summary(status)
        if dry_run:
            log.info("[DRY RUN] Would send %s alert: %s", result.level, result.reason)
        else:
            sent = notifier.send_alert(result.level, result.reason, summary)
            _record_notification(result.level, result.reason, summary, sent)

    # Emergency shutoff (only if enabled and streak threshold met)
    if (
        result.level == AlertLevel.CRITICAL
        and _critical_streak >= _shutoff_required
        and config.get("emergency_shutoff", {}).get("enabled", False)
        and not dry_run
    ):
        _trigger_shutoff(client, notifier, config, status)

    return result


def _sleep_until_next_slot(interval: int) -> None:
    """Sleep until the next wall-clock-aligned poll slot.

    Aligns to boundaries that are offset half an interval from the top of the hour.
    For a 1800s (30-min) interval this puts polls at H:15 and H:45.
    """
    now = time.time()
    # offset = interval/2 shifts the slot from H:00/H:30 → H:15/H:45
    offset = interval // 2
    elapsed_in_period = (now - offset) % interval
    sleep_for = interval - elapsed_in_period
    log.debug("Sleeping %.0fs until next aligned poll slot", sleep_for)
    time.sleep(sleep_for)


def main_loop(config: dict, dry_run: bool = False):
    """Continuous polling loop. Runs until interrupted."""
    client = _build_client(config)
    engine = Engine(config)
    notifier = NtfyNotifier(config)
    data_logger = None if dry_run else DataLogger(PROJECT_ROOT / "logs" / "metrics.csv")
    interval = config["pump"].get("poll_interval_seconds", 1800)

    log.info("Pool monitor started — polling every %ds, aligned to clock slots", interval)
    prev_running = None

    while True:
        try:
            status = client.get_status()

            # Detect pump on→off / off→on transitions
            if status is not None:
                if prev_running is False and status.is_running:
                    engine.mark_pump_start()
                prev_running = status.is_running

            result = run_once(client, engine, notifier, config, dry_run=dry_run, data_logger=data_logger)

            # Fast confirmation: first elevated reading triggers 2 more polls at short
            # intervals to confirm before the next normal poll — catches transients.
            if result and result.pending_elevated:
                log.info(
                    "Elevated reading — confirming with 2 more polls at %ds intervals",
                    FAST_CONFIRM_INTERVAL,
                )
                for _ in range(2):
                    time.sleep(FAST_CONFIRM_INTERVAL)
                    result = run_once(
                        client, engine, notifier, config,
                        dry_run=dry_run, data_logger=data_logger,
                    )
                    if result is None or not result.pending_elevated:
                        break

        except KeyboardInterrupt:
            log.info("Shutting down — goodbye")
            break
        except Exception as e:
            log.error("Unexpected error in poll cycle: %s", e, exc_info=True)
            _record_error(f"Unexpected error: {e}")

        _sleep_until_next_slot(interval)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _build_client(config: dict):
    has_creds = (
        os.environ.get("PENTAIR_EMAIL") or config.get("pentair", {}).get("email")
    )
    if not has_creds:
        log.warning("No Pentair credentials configured — using MockPentairClient.")
        return MockPentairClient()
    try:
        return PentairCloudClient(config)
    except Exception as e:
        log.error("Could not connect to Pentair cloud: %s — using MockPentairClient", e)
        return MockPentairClient()


def _log_result(result: EngineResult, status: PumpStatus):
    if result.level == AlertLevel.NORMAL:
        log.info(
            "OK [%s] RPM=%d  %.0fW  %.0f GPH  ratio=%.4f — %s",
            status.speed_mode, status.rpm, status.power_watts,
            status.flow_gph, status.watts_per_gph or 0, result.reason,
        )
    elif result.level == AlertLevel.WARN:
        log.warning(
            "WARN [%s] RPM=%d  %.0fW  %.0f GPH — %s",
            status.speed_mode, status.rpm, status.power_watts,
            status.flow_gph, result.reason,
        )
    else:
        log.error(
            "CRITICAL [%s] RPM=%d  %.0fW  %.0f GPH — %s  (streak=%d)",
            status.speed_mode, status.rpm, status.power_watts,
            status.flow_gph, result.reason, _critical_streak,
        )


def _status_summary(status: PumpStatus) -> str:
    return (
        f"RPM: {status.rpm}  |  Power: {status.power_watts:.0f}W  |  "
        f"Flow: {status.flow_gph:.0f} GPH  |  Mode: {status.speed_mode}"
    )


def _trigger_shutoff(client, notifier: NtfyNotifier, config: dict, status: PumpStatus):
    delay = config.get("emergency_shutoff", {}).get("delay_seconds", 30)
    log.error("EMERGENCY SHUTOFF — confirmed CRITICAL pressure. Turning off in %ds.", delay)
    notifier.send_alert(
        AlertLevel.CRITICAL,
        f"\U0001f534 PUMP SHUTOFF in {delay}s — sustained critical pressure confirmed.\n"
        f"Check filter and skimmer basket immediately.",
        _status_summary(status),
    )
    time.sleep(delay)
    client.turn_off()
    time.sleep(3)
    success = client.set_pump_enabled(False)
    if success:
        log.error("Pump stopped and Status switch turned OFF — pump will not auto-restart.")
        notifier.send_alert(
            AlertLevel.CRITICAL,
            f"\U0001f534 Pump has been turned OFF and schedule disabled. Re-enable in the Pentair app after clearing the blockage.",
            _status_summary(status),
        )
        shutoff_log = PROJECT_ROOT / "logs" / "shutoff.log"
        shutoff_log.parent.mkdir(parents=True, exist_ok=True)
        import datetime as _dt
        with open(shutoff_log, "a") as f:
            f.write(json.dumps({
                "ts": _dt.datetime.now().isoformat(),
                "status": {
                    "rpm": status.rpm,
                    "power_watts": status.power_watts,
                    "flow_gph": status.flow_gph,
                    "speed_mode": status.speed_mode,
                },
            }) + "\n")
    else:
        log.error("Emergency shutoff FAILED — could not set Pump Status switch via API.")
        notifier.send_alert(
            AlertLevel.CRITICAL,
            "\U0001f534 SHUTOFF FAILED — could not reach pump API. Turn off manually immediately.",
            _status_summary(status),
        )


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Pool Filter Monitor")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--once", action="store_true", help="Single poll then exit")
    parser.add_argument("--dry-run", action="store_true", help="Don't send notifications")
    parser.add_argument("--test-notify", action="store_true", help="Send test ntfy message and exit")
    parser.add_argument("--test-shutoff", action="store_true", help="Test emergency shutoff with 5s warning delay")
    parser.add_argument("--dump-raw", action="store_true", help="Print all raw API fields from the device and exit")
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging(config)

    if args.test_notify:
        notifier = NtfyNotifier(config)
        ok = notifier.send_test()
        sys.exit(0 if ok else 1)

    if args.dump_raw:
        client = _build_client(config)
        client.get_status()  # triggers device discovery
        raw = client._raw_status() if hasattr(client, "_raw_status") else None
        if raw is None:
            log.error("Could not fetch raw status")
            sys.exit(1)
        fields = raw.get("fields", {})
        print(f"\n{'Field':<12} {'Value':<40} Display")
        print("-" * 70)
        for k in sorted(fields.keys()):
            v = fields[k]
            val = v.get("value", "") if isinstance(v, dict) else v
            disp = v.get("displayName", "") if isinstance(v, dict) else ""
            print(f"{k:<12} {str(val):<40} {disp}")
        sys.exit(0)

    if args.test_shutoff:
        client = _build_client(config)
        notifier = NtfyNotifier(config)
        status = client.get_status()
        if status is None:
            log.error("Cannot test shutoff — pump unreachable.")
            sys.exit(1)
        log.warning("TEST SHUTOFF — using 5s delay instead of %ds",
                    config.get("emergency_shutoff", {}).get("delay_seconds", 30))
        override = dict(config)
        override["emergency_shutoff"] = {**config.get("emergency_shutoff", {}), "delay_seconds": 5}
        _trigger_shutoff(client, notifier, override, status)
        sys.exit(0)

    if args.once:
        client = _build_client(config)
        engine = Engine(config)
        notifier = NtfyNotifier(config)
        if not args.dry_run:
            _load_state(engine, notifier)
        data_logger = None if args.dry_run else DataLogger(PROJECT_ROOT / "logs" / "metrics.csv")

        result = run_once(client, engine, notifier, config, dry_run=args.dry_run, data_logger=data_logger)

        # Fast confirmation: first elevated reading triggers 2 more polls at short
        # intervals before alerting — rules out priming spikes and transients.
        if result and result.pending_elevated:
            log.info(
                "Elevated reading — confirming with 2 more polls at %ds intervals",
                FAST_CONFIRM_INTERVAL,
            )
            for _ in range(2):
                time.sleep(FAST_CONFIRM_INTERVAL)
                result = run_once(
                    client, engine, notifier, config,
                    dry_run=args.dry_run, data_logger=data_logger,
                )
                if result is None or not result.pending_elevated:
                    break

        if not args.dry_run:
            _save_state(engine, notifier)
        sys.exit(0 if result is not None else 1)

    main_loop(config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

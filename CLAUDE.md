# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all tests (fully offline — no pump or ntfy required)
python -m pytest tests/ -v

# Run a single test file
python -m pytest tests/test_engine.py -v

# Run a single test by name
python -m pytest tests/test_engine.py::test_alert_fires_after_three_consecutive -v

# Single poll, live pump (no notifications)
python -m monitor.runner --once --dry-run

# Single poll with notifications
python -m monitor.runner --once

# Continuous loop (for always-on hosts)
python -m monitor.runner

# Send test push notification
python -m monitor.runner --test-notify

# Serve the dashboard locally (from project root)
python -m http.server 8081
# Then open http://localhost:8081/index.html
```

The launchd service `com.james.pool-dashboard` serves the dashboard at port 8081 from the project root on this machine.

## Architecture

### Data flow

```
Pentair Cloud API → api_client.py → runner.py → engine.py → notifier.py
                                         │              │
                                    data_logger.py   recalibrator.py
                                    (metrics.csv)    (auto-updates config.yaml)
                                         │
                                    trend.py
                                    (pre-alert warnings)
```

`runner.py` orchestrates everything. `run_once()` is the core testable unit — it accepts injected `client`, `notifier`, and `engine` instances, making tests fully offline. `main_loop()` runs `run_once()` on a schedule; `--once` mode runs it once and exits.

### State persistence across cron invocations

`--once` mode (cron) exits after each poll but the rolling window (size = `consecutive_readings_required`, default 3) must persist between runs. `runner.py` saves `logs/state.json` after every poll and calls `engine.seed_window()` on startup to restore it. Without this, cron mode would always start with an empty window and require 3 fresh readings to fire any alert.

### Speed modes

The engine treats `low` and `high` speed completely separately — each has its own `baseline_watts_per_gph`, `alert_ratio_pct`, and `emergency_ratio_pct` in `config.yaml`. Speed mode is derived in `PumpStatus.__post_init__` from RPM (< 1500 = low). Two edge-case profiles in `profiles.py` are excluded from alerting and recalibration:
- **high-program-low-speed**: high-speed program is ramping up (RPM still < 1500, watts < 150W)
- **bypass/drain**: ratio implausibly low (hose or drain connected — unsafe for baseline learning)

### Fast confirmation

When engine detects an elevated raw reading, `runner.py` schedules two additional polls at 2-minute intervals before returning to the normal 30-minute schedule. All 3 confirmations must be elevated for an alert to fire. This window is the same `consecutive_readings_required` window — no separate logic.

### Auto-recalibration

`recalibrator.py` watches for the signature of a filter cleaning: a sustained elevated period followed by a sharp drop back to near-baseline. When detected, it computes the new clean-filter mean and rewrites `config.yaml` in-place using regex (not a YAML library, to preserve comments and structure). It also appends to `logs/recalibrations.json` and calls `engine.update_baseline()` so the running process uses the new value immediately.

### Dashboard

`index.html` is a self-contained static file — no build step, no backend. It reads these files directly via `fetch()`:
- `logs/metrics.csv` — one row per pump poll (written by `DataLogger`)
- `logs/notifications.json` — alert history (written by `NtfyNotifier`)
- `logs/errors.json` — non-fatal issues logged by runner
- `logs/recalibrations.json` — auto-recalibration events

The JS recomputes clean-filter baselines client-side from the CSV using the 10th-percentile W/GPH ratio per 200-GPH flow bucket. `KWH_RATE` at the top of the script is the only user-configurable constant.

### API client

`PentairCloudClient` in `api_client.py` is partially a stub — the AWS Cognito auth flow and device discovery are stubbed until Phase 1 MITM capture is complete (see `docs/api_notes.md`). `MockPentairClient` accepts a list of fixture JSON paths and cycles through them; all tests use this. Fixture files live in `tests/fixtures/`.

## Algorithm Notes

The restriction percentage shown in the dashboard and used for alerting is:

```
restriction_pct = (actual_ratio / baseline_ratio - 1) × 100
```

where `actual_ratio = power_watts / flow_gph`. A value of 0% means filter is clean (at baseline); +100% means the pump is working twice as hard per unit flow. Alert fires at `alert_ratio_pct` (default 100%) after `consecutive_readings_required` consecutive elevated readings.

Baselines are speed-mode-specific because the pump's efficiency curve differs significantly between low and high speed programs.

## Local Tools

- `observations.md` — code smell log. Add findings under `## Open`; `/smell-fix` processes it.
- `logs/recalibrations.json` — audit log of every auto-recalibration with old/new baselines.
- `logs/shutoff.log` — emergency pump shutoff audit log.

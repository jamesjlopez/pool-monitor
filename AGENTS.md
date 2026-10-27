# Agent instructions

Shared project guidance for coding agents. `CLAUDE.md` imports this file for
Claude Code versions and sessions that do not load `AGENTS.md` directly.

## Commands

Run from the project root:

```bash
# Offline tests; no pump or ntfy required
python -m pytest tests/ -v
python -m pytest tests/test_engine.py -v

# Dashboard, including shared maintenance history
python -m monitor.dashboard_server 8081
# Open http://localhost:8081/index.html

# Live pump read, with notifications and shutoff suppressed
python -m monitor.runner --once --dry-run

# Live operation (can notify and stop the pump under configured safeguards)
python -m monitor.runner --once
python -m monitor.runner

# Send a test push notification
python -m monitor.runner --test-notify
```

Use offline tests for routine verification. Tests isolate runtime files from
live logs; preserve that isolation when adding coverage.

## Current architecture

- `monitor/api_client.py`: implemented Pentair cloud authentication, discovery,
  telemetry, and pump commands. `MockPentairClient` cycles fixture files for tests.
- `monitor/runner.py`: orchestrates polling, state persistence, logging, alerts,
  and safety checks. `run_once()` accepts injected dependencies for offline tests.
- `monitor/hydraulic_quality.py`: classifies hydraulic source readings; repeated
  cloud snapshots do not count as independent measurements.
- `monitor/return_flow.py`: same-program flow references and phone advisories.
- `monitor/flow_safety.py`: separate severe low-flow emergency-stop safeguard.
- `monitor/engine.py`: pressure and calibrated-flow checks, freshness, startup
  grace, and confirmation windows. Pressure alerts require verified mapping.
- `monitor/data_logger.py`: writes dashboard metrics to `logs/metrics.csv`.
- `monitor/notifier.py`: sends ntfy notifications to subscribed clients.
- `monitor/recalibrator.py`: records candidate cleaning events for review;
  baseline application requires explicit `auto_apply=True`.
- `index.html`: HTML/CSS/JS dashboard with Chart.js; no frontend build step.
- `monitor/dashboard_server.py`: serves the dashboard and GET/POST
  `/api/maintenance`, persisting typed records in `logs/maintenance.json`.

The dashboard also fetches metrics, notifications, errors, recalibration events,
and `config.yaml`. A plain static server cannot save shared maintenance entries.
Service installation recipes live in `scripts/`.

## Measurement and safety rules

Routine polling is configured at five-minute intervals, with two-minute fast
confirmations for suspicious readings. Hydraulic source updates have been roughly
hourly; polling more often does not produce new source measurements. Honor source
timestamps, freshness checks, and API backoff.

Return-flow loss is `(1 - actual_flow / reference_flow) * 100`. The reference is
the 90th-percentile flow from at least five verified readings at the same program,
reference type, and setpoint in retained history. It is an observed reference,
not proof of a clean filter. `dashboard_return_flow` in `config.yaml` controls
both dashboard and phone thresholds: watch 15%, check 25%, inspect 40%, confirmed
by two independent hydraulic updates. Keep dashboard and Python behavior aligned.

Legacy watts-per-GPH restriction calculations are not the current dashboard or
return-flow advisory signal. Their configured baselines are unset. Cleaning
records are explicit maintenance markers; telemetry changes alone must not
silently establish a new clean baseline.

`flow_safety` independently permits an emergency stop at 600 GPH or less with
valid flow and power source readings no older than ten minutes, outside startup
grace. Pressure-based shutoff is disabled in the checked-in configuration.
Command acceptance is not physical verification of a stopped motor. See
`docs/water-starvation-2026-10-01.md` for evidence and limitations.

Persisted engine state in `logs/state.json` restores confirmation windows,
telemetry checkpoints, and notification cooldowns across single-poll invocations.
Return-flow delivery state is separate in `logs/flow-alert-state.json`. Preserve
both restart behavior and independent-reading confirmation.

## Repository housekeeping

- Keep credentials in ignored `.env` files; `.env.example` is the setup template.
- Keep runtime readings, notification history, and local state out of commits.
- `observations.md`, when present, tracks open code smells under `## Open`.
- `.agents/skills/` holds shared skill sources. `.claude/skills/typesafe-ai` is a
  relative symlink to that same skill, not a separate copy; keep it for Claude
  discovery. `skills-lock.json` records the upstream source.
- The README's current-monitoring section supersedes its historical ratio-design
  notes. Check implementation and config before copying older descriptions.

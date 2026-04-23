# Pool Filter Monitor

Automated iOS push notifications when your pool filter needs cleaning — before the pump burns out.

## The Problem

A Pentair IntelliFlo/Pro3 VSF pool pump runs on a schedule (low speed most of the day, high speed midday). Downstream is a filter canister with a physical pressure gauge. When leaves, seed pods, and debris clog the filter — or when wind fills the skimmer basket — backpressure rises and the pump overworks. Left unnoticed, this burns out the pump motor (already happened once).

The pump has WiFi (via Pentair IntelliConnect adapter) and the Pentair Home iOS app shows real-time RPM, power (watts), and flow rate (GPH). There is no digital pressure sensor — only a physical PSI gauge on the filter canister.

## The Solution

This system polls the Pentair cloud API on a schedule and estimates filter pressure indirectly from the **watts-per-GPH efficiency ratio**. When the filter clogs, backpressure increases: the pump works harder (watts rise) while flow holds steady (flow-control mode) or drops (speed-control mode), causing the ratio to rise above a calibrated baseline.

When the ratio exceeds configured thresholds, the system sends an iOS push notification via [ntfy](https://ntfy.sh). An optional emergency shutoff can turn the pump off via the API if pressure is dangerously high.

```
Pentair cloud API  ──▶  Poll every 30 min (7am–9pm)  ──▶  Engine (ratio analysis)
                                                                  │
                                                        ┌─────────┴──────────┐
                                                     NORMAL              WARN / CRITICAL
                                                     (log)                    │
                                                                         ntfy push
                                                                        (iOS phone)
```

## How It Works

The pump runs in **flow-control mode**: it adjusts RPM automatically to maintain a target GPH. A clogged filter forces the pump to spin faster (more watts) to hold the same flow. The ratio `power_watts / flow_gph` rises predictably with filter backpressure — no pressure sensor needed.

**Calibrated baselines (2026-04-19, filter at cleaning threshold):**

| Speed mode | PSI at calibration | Watts  | GPH | Baseline ratio |
|------------|--------------------|--------|-----|----------------|
| Low        | 12 PSI (alert pt)  | ~403 W | 705 | 0.570 W/GPH    |
| High       | ~18 PSI            | ~601 W | 854 | 0.704 W/GPH    |

> After cleaning the filter, re-run both speed modes and update `baseline_watts_per_gph` in `config.yaml` to the new (lower) clean-filter readings. This shifts alerting earlier — you'll be notified before reaching the old thresholds.

## Alert Thresholds

| Speed mode | WARN (clean filter soon) | CRITICAL (severe blockage) |
|------------|--------------------------|---------------------------|
| Low speed  | ratio +5% above baseline | ratio +40% above baseline |
| High speed | ratio +5% above baseline | ratio +40% above baseline |

- **Fast confirmation on first elevated reading:** rather than waiting for 3 readings at 30-minute intervals (90 minutes), the monitor polls twice more at 2-minute intervals the moment an elevated reading is detected. All 3 confirmations happen within ~4 minutes, then the alert fires. This catches sudden events quickly — a storm dropping leaves into the skimmer, water level dropping, or a startup pressure spike — without false positives from transients.
- **Startup spike protection:** if the elevated reading occurred during pump priming, the 2-minute confirmation polls will come back normal and no alert is sent.
- **120-second startup grace period** — all alerts suppressed for 2 minutes after the pump starts.
- **30-minute cooldown** between repeat WARN alerts — CRITICAL always fires immediately.
- WARN sends a high-priority iOS notification (⚠️); CRITICAL sends an urgent alert that bypasses silent mode (🚨).
- **Emergency shutoff:** if all 3 confirmation readings are CRITICAL, the pump is turned off via the API after a 30-second warning notification. A follow-up notification confirms the pump stopped (or instructs manual shutoff if the API call fails).

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
# Edit .env and set PENTAIR_EMAIL and PENTAIR_PASSWORD
```

The runner auto-loads `.env` on startup — no shell sourcing required.

### 3. Configure ntfy

Install the [ntfy app](https://ntfy.sh) on your iPhone and subscribe to your topic. The default topic in `config.yaml` is `pool_monitor_project` — change it to something private.

### 4. Test notifications

```bash
python -m monitor.runner --test-notify
```

You should receive a test notification on your phone within a few seconds.

### 5. Verify live polling

```bash
python -m monitor.runner --once --dry-run
```

This polls the pump and logs the result without sending any notifications. Confirm you see a line like:

```
OK [low] RPM=1441  403W  705 GPH  ratio=0.5716 — Normal — ratio 0.5716 W/GPH (+0% vs baseline)
```

### 6. Install cron job

```bash
crontab -e
```

Add this line (adjust the Python path if needed):

```
*/30 7-20 * * * cd /path/to/pool_monitor_project && /path/to/python -m monitor.runner --once >> logs/cron.log 2>&1
```

This polls every 30 minutes from 7:00am to 8:30pm — covering the full pump schedule (7am–9pm) without over-polling the API.

## Architecture

```
pool_monitor_project/
├── config.yaml              # thresholds, ntfy topic, poll interval
├── .env                     # credentials (gitignored)
├── monitor/
│   ├── types.py             # shared dataclasses: PumpStatus, AlertLevel, EngineResult
│   ├── engine.py            # speed-aware anomaly detection (watts/GPH ratio analysis)
│   ├── api_client.py        # Pentair cloud API client (AWS Cognito + REST)
│   ├── notifier.py          # ntfy push notification sender with cooldown deduplication
│   └── runner.py            # main loop + run_once() (core testable unit)
├── tests/
│   ├── fixtures/            # sample pump API responses for offline testing
│   ├── test_engine.py
│   ├── test_notifier.py
│   ├── test_api_client.py
│   ├── test_runner.py
│   └── test_integration.py
├── scripts/
│   ├── install_service.sh        # optional systemd service installer (for always-on hosts)
│   └── send_test_notification.py # ntfy smoke test
└── logs/
    ├── cron.log             # cron job output
    ├── pool_monitor.log     # rotating log file (5 MB × 3)
    └── shutoff.log          # emergency shutoff audit log
```

## Running

```bash
# Single poll (with notifications)
python -m monitor.runner --once

# Single poll, no notifications
python -m monitor.runner --once --dry-run

# Continuous loop (for always-on hosts — use systemd service)
python -m monitor.runner

# Send test notification and exit
python -m monitor.runner --test-notify
```

## Development

```bash
# Run all tests (no pump required — uses mock client and fixture files)
python -m pytest tests/ -v
```

## Deploying on a dedicated host

For always-on monitoring (Raspberry Pi, Mac Mini, etc.):

```bash
git clone <repo>
pip install -r requirements.txt
cp .env.example .env   # fill in credentials
./scripts/install_service.sh   # installs systemd service
```

The systemd service runs the continuous loop with auto-restart on failure. The cron approach above also works on any Linux host.

## Suggestions for next steps

**Recalibrate after cleaning the filter**

The current baselines were measured with the filter at ~12 PSI (cleaning threshold), not on a clean filter. After the next backwash:

1. Let the pump run for a few minutes to stabilize
2. Note the new ratio at low speed: `python -m monitor.runner --once --dry-run`
3. Switch to high speed manually and run `--once --dry-run` again
4. Update both `baseline_watts_per_gph` values in `config.yaml`

This shifts alerting to the actual "filter getting dirty" point rather than "filter already at the cleaning threshold." You'll get warnings earlier and the cost chart delta will be meaningful from day one.

**Deploy to a dedicated always-on host**

The current WSL setup only monitors while your Windows machine is running. A dedicated host gives true 24/7 coverage. Good options:

- **Raspberry Pi Zero 2W** (~$15) — lowest power draw, runs Linux natively, no WSL quirks. Ideal for a single always-on background task.
- **Raspberry Pi 4/5** — if you want to run other services alongside it.
- **Mac Mini** — if you already have one running.

Setup on any Linux host is the same cron approach:

```bash
git clone <repo>
pip install -r requirements.txt
cp .env.example .env      # fill in credentials
crontab -e                # paste the cron line from the Setup section
```

Or use the included systemd service for auto-restart on failure:

```bash
./scripts/install_service.sh
```

---

## Design decisions

**Why watts/GPH ratio instead of direct PSI?**
The pump's API exposes RPM, watts, and flow — but not filter pressure. A clogged filter increases backpressure, which forces the pump to work harder for the same flow. The watts/GPH ratio rises predictably with blockage, making it a reliable pressure proxy without any additional hardware.

**Why set the baseline at the cleaning threshold, not clean-filter state?**
The filter was at 12 PSI (cleaning threshold) when first calibrated. Setting the baseline there with a tight 5% alert band means any further clogging fires a WARN immediately. After cleaning, the baseline will be reset to the lower clean-filter ratio, giving earlier warnings in future.

**Why fast confirmation at 2-minute intervals instead of waiting for 3 polls at 30 minutes?**
Waiting three 30-minute polling cycles (90 minutes) to confirm clogging is too slow for sudden events — a storm dropping leaves into the skimmer, water level dropping, or a pump blockage can cause real damage in minutes. The fast confirmation approach polls twice more at 2-minute intervals the moment an elevated reading is detected. If all 3 readings confirm the problem, the alert fires within ~4 minutes. If the confirmations come back normal (e.g., a startup pressure spike), no alert is sent. This gives rapid response without false positives.

**Why the startup grace period?**
The pump primes at higher pressure for ~2 minutes when it starts. Without a grace period, every scheduled startup would trigger a false alert.

**Why cloud API instead of local?**
The Pentair IntelliConnect adapter communicates exclusively via Pentair's AWS cloud — there is no local HTTP API. The app uses certificate pinning, so traffic interception is not practical. Authentication uses AWS Cognito with credentials reverse-engineered from the Pentair Home community.

**Emergency shutoff is enabled and triggers on confirmed CRITICAL readings.**
After 3 fast-confirmed CRITICAL readings (~4 minutes of sustained extreme pressure), the pump is turned off via the API following a 30-second warning notification. A follow-up notification confirms the outcome. The pump must be restarted manually after clearing the blockage.

## License

MIT

# Pool Monitor — Progress Punch List

Resume here if implementation is interrupted. Check items off as they are completed.

## Status: Implementation complete — awaiting Phase 1 API discovery

---

## Completed

- [x] **Phase 0** — `requirements.txt`, `config.yaml`
- [x] **monitor/types.py** — shared `PumpStatus`, `AlertLevel`, `EngineResult` dataclasses
- [x] **monitor/engine.py** — speed-aware anomaly detection (watts/GPH ratio, rolling window, grace period)
- [x] **monitor/notifier.py** — ntfy push notifications with deduplication and cooldown
- [x] **monitor/api_client.py** — `PentairClient` stub + `MockPentairClient` for testing
- [x] **monitor/runner.py** — `run_once()` + `main_loop()` + CLI (`--once`, `--dry-run`, `--test-notify`)
- [x] **monitor/discover.py** — mitmproxy addon that logs all traffic, highlights pump telemetry
- [x] **monitor/sniffer_setup.sh** — updated to support `discover` and `monitor` modes
- [x] **tests/fixtures/** — 6 fixture files: low/high × clean/clogged/off/startup
- [x] **tests/test_engine.py** — 22 unit tests: thresholds, grace period, rolling window, calibration
- [x] **tests/test_notifier.py** — 10 tests: send, cooldown, deduplication, priorities
- [x] **tests/test_api_client.py** — 12 tests: fixtures, field extraction, sequence looping
- [x] **tests/test_runner.py** — 5 tests: run_once with injected deps
- [x] **tests/test_integration.py** — 6 scenario tests: clean/clogged/startup/mixed/high-speed
- [x] **scripts/send_test_notification.py** — smoke test for ntfy
- [x] **scripts/install_service.sh** — systemd unit installer
- [x] **docs/api_notes.md** — discovery template (fill in after Phase 1)
- [x] **analysis/extractor_template.py** — extended with RPM extraction and calibration output
- [x] **README.md** — project overview, setup guide, architecture, design decisions

---

## Blocked: Needs your action

### NEXT STEP — Phase 1: API Discovery

The `monitor/api_client.py` is a **stub** and the live pump client will not work until you complete this step.

**What to do:**

1. Make sure this machine is on the same WiFi network as the pump

2. Install dependencies if not already done:
   ```bash
   cd /home/james/.openclaw/workspace/pool_monitor_project
   pip install -r requirements.txt
   ```

3. Start the discovery proxy:
   ```bash
   ./monitor/sniffer_setup.sh discover
   ```

4. On your iPhone:
   - Settings > Wi-Fi > your network > Configure Proxy > Manual
   - Server: `<this machine's LAN IP>` (shown when you run the script)
   - Port: `8080`

5. Visit `http://mitm.it` in Safari → install the mitmproxy CA cert
   Then: Settings > General > About > Certificate Trust Settings → enable it

6. Open the **Pentair Home** app:
   - Navigate to pump status (triggers a status poll)
   - Wait 60 seconds for a background refresh
   - Optionally change speed or view settings (captures control endpoints)

7. Press Ctrl-C on the proxy

8. Inspect:
   ```bash
   cat logs/discovery/telemetry_*.jsonl | python3 -m json.tool | less
   ```

9. Fill in `docs/api_notes.md` with:
   - Base URL (local IP or cloud domain)
   - Auth headers
   - JSON field names for RPM, watts, GPH

10. Update `monitor/api_client.py`:
    - `PUMP_STATUS_ENDPOINT`
    - `_build_headers()`
    - `_parse_status()`
    - `self._base_url`

11. Set `pump.host` in `config.yaml`

---

## Remaining implementation tasks (after Phase 1)

- [ ] Fill in `monitor/api_client.py` with real endpoints (after API discovery)
- [ ] Update fixture files in `tests/fixtures/` with real API response format
- [ ] Run tests against real client: `python -m monitor.runner --once --dry-run`
- [ ] Send test notification: `python scripts/send_test_notification.py`
- [ ] Observe pump for a few days on clean filter → note watts/GPH ratios in logs
- [ ] Set `baseline_watts_per_gph` in `config.yaml` (or run calibration via screenshot OCR)
- [ ] Install systemd service: `./scripts/install_service.sh`
- [ ] After reliable operation: consider enabling emergency shutoff in `config.yaml`

---

## Verification checklist

- [ ] `python -m pytest tests/ -v` — all tests pass (no pump needed)
- [ ] `python scripts/send_test_notification.py` — notification arrives on phone
- [ ] `python -m monitor.runner --once --dry-run` — polls pump, logs a reading
- [ ] Simulate clog by lowering `alert_ratio_pct` to 0 → verify notification fires
- [ ] Confirm startup grace: restart pump → no alert for 2 minutes
- [ ] Confirm cooldown: trigger WARN → same level suppressed for 30 min

# Water-starvation report — October 1, 2026

Times below are America/Chicago (CDT).

James observed air bubbles at the return and unusual pump noise at about 11:07.
A chlorine-tablet floater partially obstructed the skimmer, and leaves were in
the skimmer basket. Moving the floater and emptying the basket did not immediately
restore normal operation. The pump basket was not full of water. James suspected
low pool water, stopped the pump, began filling with a hose, and planned to
restart manually after about two hours. Low water is a hypothesis, not a measured
fact. James confirmed that onboard Dry Run and Loss of Prime protection are enabled.

## What was detectable

The CSV and notification log show reduced flow before the incident:

| Poll time | Flow (GPH) | Power (W) | Flow source time |
|---|---:|---:|---|
| 07:15 | 2,652 | 502 | 07:08:10 |
| 08:15 | 2,394 | 490 | 08:08:09 |
| 09:15 | 2,646 | 490 | 09:08:10 |
| 10:15 | 2,562 | 496 | 10:08:09 |
| 11:02 | 2,562 | 496 | 10:08:09 (repeated) |

At 08:45:03, ntfy accepted an advisory for flow 32% below the recent low-speed
reference of 3,510 GPH. The monitor therefore detected reduced flow earlier,
but not its cause. It does not measure skimmer water level, air ingestion, or noise.

The final pre-incident flow measurement was almost 59 minutes old at 11:07.
Power's last source timestamp was 10:12:08. Repeated HTTP polls did not produce
new hydraulic readings. There is no captured low/no-flow sample proving when
starvation began. The 11:15 application log reports zero workload with the master
switch disabled, consistent with the user's intervention, not a dry-running sample.

## Why automatic shutoff did not happen

The old engine only escalated zero flow after two independent readings; ordinary
flow loss was advisory only. The runner's shutdown path required both
`emergency_shutoff.enabled` and `pressure_mapping_verified`, both false in the
active configuration. This incorrectly made even a zero-flow stop depend on
pressure calibration. Independently, no qualifying zero-flow reading was captured
before the manual stop, so enabling that path alone would not have caught this event.

## Protection added

`monitor/flow_safety.py` provides a separate, enabled emergency rule for valid,
recent powered-pump readings at or below 600 GPH. This floor is a conservative
policy choice, not a threshold learned from this incident. No fresh powered-pump
rows in the retained CSV met this floor when checked; historical non-triggering
is not proof that the threshold detects every dangerous condition.

It acts on one qualifying reading, respects the bounded observed-start priming
grace, ignores pressure calibration, issues both stop commands before notification,
and preserves unsuccessful disable requests for later retry. Polling changes from
30 minutes plus stale retries to a regular two-minute schedule. No command ever
starts or re-enables the pump.

Tests cover the parsed live-data format, the uncalibrated-pressure configuration,
zero and severe low flow, stale/missing/invalid inputs, disabled master switch,
priming grace and expiry, dry runs, notification failure, independent command
failures, command order, and persistent retry across new engine instances.

## Remaining limitation

This incident cannot be retrospectively classified as a detectable emergency from
the available telemetry. The new guard would not trip on its recorded pre-incident
values either. Reliable rapid protection requires timely local measurements or
the pump's own protection. An enabled onboard feature is not evidence that it
detected this event.

Pentair's guide explains that Loss of Prime can pause and attempt to re-prime;
it does not necessarily mean an immediate permanent shutdown. Have the actual
priming settings and suction-side behavior checked if air/noise recurs despite
these features being enabled. Source: [Pentair IntelliFlo3/IntelliPro3 user guide,
Priming Parameters](https://www.pentair.com/content/dam/extranet/nam/pentair-pool/residential/pumps/intelliflo3-vsf/manuals/users-guide/intelliflo3-pro3-vsf-users-guide.pdf).

Changes intentionally remain uncommitted alongside pre-existing work in the same
configuration and runner files. Review was limited to this change; unrelated
dashboard and flow-advisory work was preserved.

## Activation and verification

The local `com.james.pool-monitor` service was restarted at 11:19:49. It
authenticated successfully, logged the new 120-second polling interval at
11:19:54, and read the master switch disabled with zero workload at 11:19:55.
The monitor service was restarted; no pump-start command or live fault injection
was performed. Shutoff and urgent-notification behavior were tested with mocks.

## Follow-up after manual restart, approximately 11:29

James subsequently reported successful priming and running after restart, before
the pool level had visibly changed. The hose was still filling and light rain was
falling. His working hypothesis is that the floater obstructed the skimmer, possibly
in combination with low water, and the pump may have struggled since its morning
start. The successful restart without an appreciable level change makes obstruction
plausible but does not isolate a cause: the floater and leaves were removed and the
pump was also stopped and re-primed.

The four independent 07:00–11:00 samples do not support continuous failed priming:
they report 39.9–44.2 GPM, 490–502 W, and the low-speed program at 70.5% motor speed.
Configured priming speed in James's screenshot is 87%. These observations weigh
against remaining continuously in a priming cycle, but sparse measurements and
estimated flow cannot exclude intermittent air ingestion or unsuccessful intervals.

| Morning | Independent samples | Mean reported flow (GPH) | Mean power (W) |
|---|---:|---:|---:|
| September 28 | 4 | 1,821 | 462 |
| September 29 | 4 | 2,373 | 487 |
| September 30 | 4 | 2,200.5 | 480 |
| October 1 | 4 | 2,563.5 | 494.5 |

October 1's morning flow was 16.5% higher than September 30's, though still below
the recent low-speed reference. These comparison days are not certified healthy
baselines. On September 28–30, the 10:15 polls show low speed and the 11:15 polls
show high speed (85.4%). A roughly 11:00 speed increase exposing a suction restriction
is therefore another plausible hypothesis, not a captured fact for October 1.

The initial post-restart snapshot at 11:31 reports high program, 4,188 GPH, only
54 W, and 12.9% motor speed. At 11:33 it repeats the same source timestamps despite
being marked fresh in the CSV by the startup/profile path. The runner explicitly
classifies it as a low-load transition awaiting stable telemetry. It must not be
used as an independent confirmation of healthy recovery or a quantitative before/
after comparison. James's physical observation establishes the reported recovery;
the cloud has not yet provided a trustworthy stable post-restart comparison.

The emergency rule's message names possible water starvation/loss of prime, measured
power and flow, and likely inspection points; its outcome states command acceptance
or failure. It does not diagnose the floater, low water, or another specific cause.
No new shutoff threshold is justified by these additional observations. The enabled
600-GPH rule remains backup protection and would not have tripped on the morning
samples. Immediate protection from an event between cloud updates remains unmet.

## Polling adjustment approved after rate-limit discussion

Routine polling was subsequently reduced to five minutes, aligned at :00/:05/etc.
Brief two-minute confirmation checks remain. HTTP 429 telemetry responses now
cause a five-minute exponential backoff (fallback capped at one hour), honoring
longer Retry-After values in seconds or HTTP-date form. Emergency control requests
remain available. This backoff is in memory, not persisted across service restarts.
No explicit rate-limit responses were found in the examined logs.

The full suite passed (199 tests). The service restarted and logged its 300-second
interval at 11:41:48, then successfully fetched running high-speed telemetry.

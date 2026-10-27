# Skimmer basket cleaning: September 20, 2026

Initial analysis completed around 12:30 PM CDT. James reported emptying a fairly
stuffed surface skimmer basket containing leaves at **12:07 PM CDT**. This is a
basket-cleaning observation, not confirmation that the filter canister was cleaned.

## Final outcome — September 21, 12:44 PM CDT

**No measured flow improvement followed the reported skimmer-basket cleaning.**
The next day's two independent high-speed source samples (11:08:03 AM and
12:08:03 PM) were 3,084 and 3,090 GPH at the same program / reference 3 /
setpoint 854. Their median, 3,087 GPH, is 8.45% below
the single pre-cleaning September 20 high-speed sample (3,372 GPH), and
26.29% below September 17's two-sample median (4,188 GPH).
The exact 11 AM day-to-day comparison is down 8.54%. Yesterday's 12:08 PM
sample is excluded from the pre-cleaning baseline because it followed cleaning.
Compared with September 18 and 19 daily high-speed medians, today's median is
25.49% and 21.15% lower, respectively.

Today's four morning low-speed samples had median flow 2,901 GPH, versus
3,483 GPH in yesterday's four pre-cleaning morning samples: **16.71% lower**.
This is also 17.35% below September 17–19's 3,510-GPH daily low-speed medians.
Both comparisons match program, reference, and setpoint and count only new
paired pressure/flow source updates, not repeated polls.

Today's high-speed reported pressure was 17.86 and 17.79 PSI, versus 17.34
before cleaning; power was 745 and 735 W, versus 756 W. These are supporting
observations, not calibrated pressure-based diagnoses. The 12:08 PM source
sample was collected at 12:15 PM; telemetry remained available throughout
the comparison. Overnight zero/non-running readings were excluded.

The observed decline is detectable, but this event **does not validate a
leaf-obstruction signature or establish that cleaning caused the decline**.
It also cannot establish what flow would have been without cleaning. A generic
“reduced flow; check baskets and other restrictions” advisory remains better
supported than a leaf-specific diagnosis. The initial recommendation to retain
separate program histories across days still applies; production detector,
calibration, and pump controls were not changed. Notification delivery was
confirmed by James. The bounded follow-up is complete and its automation has been paused.

## Findings (initial assessment)

There is a detectable deterioration in **high-speed estimated return flow** over
the last few days. It is not yet established that the basket caused it, or that
emptying the basket reversed it. Low-speed flow shows little recent deterioration.

All comparisons below use the same named program, reference 3, and setpoint
(854 for high, 705 for low). These are motor-speed settings, not measured RPM.
Only new paired pressure/flow source updates count; repeated cloud snapshots do
not provide independent evidence. Of 1,211 retained polls, 260 were verified
running hydraulic updates. The source history starts September 2; legacy history
was excluded because of earlier field-mapping issues.

| High-speed sample or day | Estimated flow, GPH | Reported pressure, PSI | Power, W |
|---|---:|---:|---:|
| September 17 daily median (2 samples) | 4,188 | 14.22 | 771.5 |
| September 18 daily median (2 samples) | 4,143 | 14.22 | 769 |
| September 19 daily median (2 samples) | 3,915 | 15.55 | 762 |
| September 20, 11:08:02 AM source sample, before cleaning | 3,372 | 17.34 | 756 |
| September 20, 12:08:02 PM source sample, just after cleaning | 3,276 | 17.50 | 746 |

Before cleaning, flow was **19.5% below September 17**, with reported pressure
3.12 PSI higher. Power was slightly lower, so increasing watts alone would miss
this pattern. Pressure here is the API's reported value; its physical-gauge
calibration remains unverified in configuration. Flow is the pump's estimate.

The first post-cleaning sample was taken only **62 seconds after the reported
cleaning time**, although it was fetched at 12:15 PM. Flow was 2.85% lower than
the 11:08 AM sample, pressure 0.16 PSI higher, and power 1.32% lower. That is
not evidence of improvement; it is also too close to the intervention to make a
settled outcome claim. A ten-minute exclusion after cleaning is an analysis
convention, not a calibrated settling-time claim.

Low-speed daily median flow was 3,510 GPH on September 17–19. Today's four
pre-cleaning low-speed readings had a median of 3,483 GPH, only 0.77% lower.
Compare future low-speed readings to these low-speed references, never directly
to the midday high-speed readings.

The earlier history also contains a much larger decline: high-speed daily median
flow fell from 4,188 GPH on September 2 to 2,046 GPH on September 16, then was
back to 4,188 on September 17. Low-speed flow recovered on September 16. The
cause of that recovery is not established by this investigation and should not
be labeled a confirmed basket cleaning.

## Existing alerts and notification check

`monitor/suction.py` already produces “Pool Flow Change — Check Baskets” guidance.
It requires a flow drop of at least 20% plus a reported pressure increase of
at least 0.5 PSI, using at most four readings. It clears its history whenever
the program changes. Consequently, the high-speed comparison starts over each
day and misses the multiday deterioration above. Within today's high-speed
session the flow drop was only 2.85%.

Replaying all 260 verified updates through the existing detector produced one
warning, on September 3 at 7:52 PM; none during the September 17–20 decline.
This is an offline detector replay, not proof of what was delivered on those dates.

Other implementation limits to address before relying on expanded alerts:

- Detection runs in the continuous loop, outside `run_once`; fresh samples obtained
  by retry/confirmation polls do not enter this detector. Single-poll mode omits it.
- Detector history is not persisted across restarts, and an alerted episode has
  no same-program recovery reset.
- Basket warnings use low-priority `send_info`, are not added to dashboard
  notification history, and mark the episode alerted before delivery succeeds.
- Absolute clean-flow and legacy watts/flow thresholds are currently disabled
  pending calibration. Pressure-based alerts and automatic shutoff are disabled.

The configured notification service **accepted a real test push on September 20**.
The first sandboxed attempt failed; the network-authorized attempt succeeded.
James subsequently confirmed receiving the notification on his phone, verifying
end-to-end delivery through the configured notifier. All 14 existing notifier
and suction-detector tests passed. The existing test-push wording calls the
monitor active, but that message itself is not a service-health check. Recent
scheduled log entries independently show polling through 12:15 PM.

## Recommended alert behavior

Use a **possible obstruction / check baskets** advisory rather than claiming
leaves or a dirty filter have been diagnosed. The telemetry lacks a labeled
history that distinguishes basket debris, filter loading, valve changes, water
level, or other causes. Today's intervention gives us one useful labeled event.

A candidate for evaluation is a 15–20% flow decrease relative to several recent
good readings at the exact same program/reference/setpoint, confirmed by two
independent source updates. Keep separate program histories across daily schedule
changes and restarts, impose a maximum reference age, and reset confirmation at
maintenance events. Do not treat September 17 as a verified clean baseline.
Pressure change can be supporting context rather than a mandatory calibrated
threshold. Thresholds remain provisional: this history is insufficient to measure
false positives or establish a leaf-specific detector.

With a fixed September 17 reference, the 15% candidate would flag today's
11:08 sample for confirmation; the second sample is after cleaning and should
not simply complete an obsolete pre-cleaning recommendation. At 20%, the first
sample would not qualify, whereas the 12:08 sample is 21.8% below that reference.

Suggested wording once independently confirmed:

> Return flow is about 20% below its recent level at the same pump setting.
> Check the surface skimmer basket for leaves and the pump basket. If those are
> clear, check water level and other restrictions. The readings suggest reduced
> flow but cannot identify the cause.

No production thresholds or detector behavior were changed during this analysis.
The next step is to compare settled post-cleaning low-speed samples this afternoon
and matched high-speed samples tomorrow. Sustained recovery would support, but
not prove, basket obstruction as the explanation. No recovery would weaken it.

## Reproduction and follow-up

Run `.venv/bin/python analysis/skimmer_cleaning_20260920.py` from the project root.
It refreshes `logs/skimmer-cleaning-2026-09-20/verified-readings.csv` and
`daily-summary.json`, reports post-cleaning samples with source timestamps, and
does not poll, send messages, edit calibration, or touch running monitor state.
The maintenance observation is recorded separately in that directory.

### September 20, 1:27 PM CDT follow-up

One new paired update arrived: the 1:08:02 PM source sample, collected at
1:15 PM, at low speed / reference 3 / setpoint 705. Flow was 3,456 GPH,
reported pressure 10.40 PSI, and power 502 W. This is 0.78% below today's
pre-cleaning low-speed median (3,483 GPH), and 1.54% below the September 17–19
low-speed daily medians (3,510 GPH). It is within today's pre-cleaning range
of 3,420–3,510 GPH. There is no meaningful demonstrated flow recovery or
new deterioration, and one settled sample cannot establish a sustained change.
No new high-speed comparison is available. Continue the scheduled follow-up;
no user notification warranted on this check.

### September 20, 2:27 PM CDT follow-up

A second settled paired update arrived at 2:08:02 PM source time (collected
2:15 PM), at the same low-speed program / reference 3 / setpoint 705. Flow
was 3,378 GPH, reported pressure 11.18 PSI, and power 499 W. Flow is 3.01%
below today's pre-cleaning low-speed median and 3.76% below the September
17–19 low-speed daily medians. The two settled low-speed samples have a
median of 3,417 GPH (1.89% below today's pre-cleaning median; 2.65% below
the earlier reference). This small decline does not demonstrate recovery,
and is not yet a meaningful sustained deterioration warranting notification.
The new sample is slightly below today's pre-cleaning range; continue watching
rather than attributing that difference to basket debris. No settled high-speed
sample is available yet. Telemetry remains current; no user action is required.

### September 20, 3:27 PM CDT follow-up

The new 3:08:02 PM paired source update (collected 3:15 PM) at low speed /
reference 3 / setpoint 705 reports 3,066 GPH, 11.23 PSI, and 499 W. Flow
is 11.97% below today's pre-cleaning low-speed median and 12.65% below the
September 17–19 reference. This is a larger single-sample decline, following
3,456 and 3,378 GPH; it warrants checking the next independent source update.
The three settled low-speed samples have median flow 3,378 GPH, still only
3.01% below today's pre-cleaning median. There is no recovery demonstrated,
but the larger decline has not yet been independently confirmed as sustained.
No settled high-speed comparison is available. Telemetry is current. Continue
monitoring without a user notification at this check.

### September 20, 4:27 PM CDT follow-up — sustained lower flow

The 4:08:02 PM paired source sample (collected 4:15 PM), at unchanged low
speed / reference 3 / setpoint 705, reports 2,994 GPH, 11.89 PSI, and 499 W.
Flow is 14.04% below today's pre-cleaning low-speed median (3,483 GPH) and
14.70% below the September 17–19 reference (3,510 GPH). This follows the
independent 3:08 PM sample at 3,066 GPH, about 12% below today's pre-cleaning
median. Thus two independent hourly updates now corroborate a meaningful
reduction, rather than a single transient or duplicated poll.

The four settled low-speed samples descend from 3,456 to 3,378 to 3,066 to
2,994 GPH; their median is 3,222 GPH, 7.49% below today's pre-cleaning median.
Reported pressure has risen from 10.40 to 11.89 PSI over those samples, while
power is nearly flat. Physical pressure calibration remains unverified.
Basket cleaning has not produced an observed flow recovery. This does not
establish that cleaning caused the decline or identify the location/cause of
restriction. A task update is warranted for this newly sustained decline.
Telemetry is current; keep the bounded follow-up active for tomorrow's matched
high-speed comparison, without changing production alerts or pump controls.

### September 20, 5:29 PM CDT follow-up

The new 5:08:03 PM paired source update (collected 5:15 PM), at unchanged
low speed / reference 3 / setpoint 705, reports 3,066 GPH, 11.69 PSI, and
497 W. Flow remains 11.97% below today's pre-cleaning low-speed median and
12.65% below the September 17–19 reference. It is 2.40% above the preceding
sample, within the same reduced-flow range already reported at 4:27 PM.
The five settled low-speed samples have median flow 3,066 GPH. This confirms
continued lower flow but neither a meaningful additional deterioration nor
sustained recovery. Telemetry remains current. No repeat notification warranted;
continue waiting for tomorrow's matched high-speed comparison.

### September 20, 6:30 PM CDT follow-up

The 6:08:02 PM paired source sample (collected 6:15 PM), at unchanged low
speed / reference 3 / setpoint 705, reports 2,778 GPH, 12.29 PSI, and
492 W. Flow is 20.24% below today's pre-cleaning median and
20.85% below the September 17–19 reference. This is a further
single-sample decline from the previously reported 12–14% reduction. Await
another independent update before classifying the deeper loss as sustained
and sending a repeat notification. The six settled low-speed readings have
median 3,066 GPH; no recovery is demonstrated. Telemetry remains current,
and tomorrow's matched high-speed comparison remains pending.

### September 20, 7:31 PM CDT follow-up — deeper decline confirmed

The 7:08:02 PM paired source update (collected 7:15 PM) at unchanged low
speed / reference 3 / setpoint 705 reports 2,826 GPH, 12.36 PSI, and
493 W. Flow is 18.86% below today's pre-cleaning median and
19.49% below the September 17–19 reference. Together with
6:08 PM's 2,778 GPH, two independent hourly updates now confirm roughly
19–20% lower flow than the pre-cleaning median, a deeper sustained loss than
the 12–14% reduction previously reported. This merits a task update.
The seven settled low-speed samples have median flow 3,066 GPH.
No post-cleaning recovery is demonstrated; causation and restriction location
remain unknown. Telemetry is current. Continue the bounded follow-up through
tomorrow's matched high-speed comparison; production settings remain untouched.

### September 20, 8:32 PM CDT follow-up

The 8:08:03 PM paired source sample (collected 8:15 PM), at unchanged low
speed / reference 3 / setpoint 705, reports 2,730 GPH, 12.42 PSI, and
492 W. Flow is 21.62% below today's pre-cleaning median and
22.22% below the September 17–19 reference. This is 3.40%
lower than the preceding sample, remaining close to the roughly 20% loss
already reported at 7:31 PM. There is no meaningful new sustained change
warranting another notification. The eight settled low-speed samples have
median flow 3,030 GPH; no recovery has been demonstrated. Telemetry is
current. Tomorrow's matched high-speed comparison remains pending.

### September 20, 9:33 PM CDT follow-up

No new running hydraulic sample: four additional CSV polls repeat the 8:08 PM
source pair and are excluded. The runner log independently shows successful
polls at 9:15, 9:17, and 9:19 PM, reporting the cloud pump status switch
disabled with zero telemetry. This occurs at the documented end of the daytime
pump schedule, so the absence of new running flow data does not establish a
telemetry outage or additional flow deterioration. Do not compare these zero
readings against running baselines. The last valid running comparison and
maintenance outcome remain unchanged; resume assessment when running samples
return. No user notification warranted.

### September 20, 10:34 PM CDT follow-up

The refreshed analysis is unchanged: 1,255 retained polls, 268 verified running
updates, and eight settled post-cleaning low-speed samples. Runner logs show
successful polling through 10:19 PM with the cloud switch disabled and zero
telemetry, consistent with the overnight non-running period. No new comparable
measurement or actionable telemetry failure was found. Outcome unchanged;
no repeat notification. The September 21 high-speed comparison remains pending.

### September 20, 11:35 PM CDT follow-up

No new running hydraulic updates; counts and comparisons remain unchanged.
Runner logs confirm polling through 11:19 PM, still reporting the disabled
cloud switch with zero telemetry during the overnight non-running period.
No actionable telemetry failure or new outcome evidence; no notification.
Continue awaiting September 21's same-program running readings.

### September 21, 12:35 AM CDT follow-up

Analysis remains unchanged: no new running hydraulic pair. The runner continues
polling, with logs through 12:19 AM reporting the disabled cloud switch and
zero telemetry during the overnight non-running period. The last valid running
comparison is retained; zero readings are excluded. No new actionable failure
or outcome evidence, so no notification. Midday high-speed comparison pending.

### September 21, 1:36 AM CDT follow-up

No new running sample: the refreshed analysis still ends at September 20's
8:08 PM source pair. Runner logs confirm polling through 1:19 AM with the
cloud switch disabled and zero telemetry overnight. Comparisons and outcome
remain unchanged; no actionable outage or notification. Await daytime readings.

### September 21, 2:36 AM CDT follow-up

No new running hydraulic data; the last paired sample and all comparisons
are unchanged. Runner logs show polling through 2:19 AM with the disabled
cloud switch and zero telemetry during the overnight non-running period.
No actionable failure or new evidence; no notification. Daytime comparison pending.

### September 21, 3:37 AM CDT follow-up

No new running pair or change in the comparison. Runner logs confirm polling
through 3:19 AM with the cloud switch disabled and zero telemetry overnight.
No actionable outage or new outcome evidence; no notification. Continue awaiting
the scheduled daytime running samples and matched midday high-speed readings.

### September 21, 4:38 AM CDT follow-up

Analysis is unchanged, with no new running hydraulic pair. Runner logs confirm
polling through 4:19 AM with the disabled cloud switch and zero telemetry
overnight. No actionable outage or additional outcome evidence; no notification.
The daytime comparison remains pending.

### September 21, 5:39 AM CDT follow-up

No new running pair; analysis and maintenance outcome remain unchanged.
Runner logs show polling through 5:19 AM with the cloud switch disabled and
zero telemetry overnight. No actionable failure or new comparison evidence;
no notification. Await daytime running measurements.

### September 21, 6:40 AM CDT follow-up

No new running hydraulic pair before the documented 7 AM daytime schedule.
Runner logs confirm polling through 6:19 AM with the cloud switch disabled
and zero telemetry. Existing comparisons and outcome remain unchanged;
no actionable failure or notification. Check for fresh running samples after
scheduled startup, then complete the midday high-speed comparison.

### September 21, 7:41 AM CDT follow-up

Running telemetry resumed: the new paired 7:08:03 AM source sample, collected
7:15 AM at low speed / reference 3 / setpoint 705, reports 2,778 GPH,
12.29 PSI, and 511 W. Flow is 20.24% below September 20's
pre-cleaning low-speed median and 20.85% below September
17–19's reference. It remains within yesterday evening's reduced-flow range,
with no demonstrated recovery or meaningful additional deterioration. The
first morning sample alone cannot establish a new sustained trend. Telemetry
is current; no repeat notification warranted. Await the matched midday
high-speed samples. Across both days, 9 settled low-speed samples have
median flow 2,994 GPH; this pooled statistic is not a same-time-of-day comparison.

### September 21, 8:42 AM CDT follow-up

The new paired 8:08:03 AM source sample (collected 8:15 AM), at unchanged
low speed / reference 3 / setpoint 705, reports 2,874 GPH, 12.29 PSI, and
505 W. Flow is 17.48% below September 20's pre-cleaning
low-speed median and 18.12% below the September 17–19
reference. Today's two morning samples have median 2,826 GPH,
remaining in the previously reported reduced-flow range. The small uptick
from 7:08 AM does not establish sustained recovery or a meaningful new change.
All ten settled low-speed samples have median 2,934 GPH. Telemetry is
current; no repeat notification warranted. Midday high-speed comparison pending.

### September 21, 9:43 AM CDT follow-up

The new paired 9:08:03 AM source sample (collected 9:15 AM), at unchanged
low speed / reference 3 / setpoint 705, reports 3,054 GPH, 12.04 PSI, and
503 W. Flow is 12.32% below September 20's pre-cleaning
low-speed median and 12.99% below the September 17–19
reference. Morning flow has risen from 2,778 to 2,874 to 3,054 GPH, suggesting
partial improvement from last evening. Only the newest reading reaches this
higher level; sustained recovery toward the pre-cleaning reference is not yet
confirmed. Today's three-sample median is 2,874 GPH. No repeat
notification warranted yet; check the next independent sample. Telemetry is
current and the midday high-speed comparison remains pending.

### September 21, 10:43 AM CDT follow-up

The new paired 10:08:03 AM source sample (collected 10:15 AM), at unchanged
low speed / reference 3 / setpoint 705, reports 2,928 GPH, 11.68 PSI, and
506 W. Flow is 15.93% below September 20's pre-cleaning
low-speed median and 16.58% below September 17–19's reference.
The drop from 9:08 AM's 3,054 GPH does not confirm continued recovery. Today's
four morning readings have median 2,901 GPH, 16.71%
below the equivalent four pre-cleaning morning readings yesterday. Flow remains
reduced, with modest fluctuations rather than a meaningful new sustained change
since the last notification. Telemetry is current; no repeat notification.
Await the two midday high-speed samples for the final comparison.

### September 21, 11:44 AM CDT follow-up

The first settled high-speed comparison is available: paired source timestamps
11:08:03 AM, collected 11:15 AM, at high speed / reference 3 / setpoint 854.
It reports 3,084 GPH, 17.86 PSI, and 745 W. Flow is 8.54%
below September 20's pre-cleaning 11:08 AM sample (3,372 GPH), and
26.36% below September 17's high-speed reference (4,188 GPH).
It is also below the September 18 and 19 daily high-speed medians (4,143 and
3,915 GPH). Reported pressure is 0.52 PSI above the pre-cleaning same-hour
sample, with calibration still unverified. This first matched sample does not
show recovery. Await the second midday high-speed source update before the
final bounded comparison and automation pause. Telemetry is current; no
interim notification warranted for this single new high-speed sample.

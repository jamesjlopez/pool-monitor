# Repeated polls are not expired hydraulic readings

**Surfaced:** pool-monitor live dashboard diagnosis, 2026-09-05.

The September 4–5 live CSV contained 14 paired hydraulic updates and 56
repeated/mixed polls over approximately 24 hours. During daytime operation,
pressure and flow source timestamps advanced hourly, near seven minutes past
the hour. Normal polls and bounded retries therefore often repeated a valid
pair. Requiring the latest poll to advance both fields made the hero show
“Hydraulic readings are stale” for most of each hour.

Keep two separate decisions: whether an observation is new enough to count in
analytics/alert evaluation, and whether a previously verified pair is still
recent enough to display. The hero can reuse the verified pair only when both
source timestamps, hydraulic values, and operating context still match. Its
age comes from the older pressure/flow source timestamp, never the poll time.
Use the configured 90-minute limit; expiry must also work when polling stops.
Do not loosen historical classification or fill chart gaps to fix the hero.

Regression checks in `tests/test_dashboard.py` run the actual CSV parser,
derived calculations, and hero renderer with a minimal DOM and controlled
clock. Live verification fetches both HTML and CSV from the served dashboard
and runs that same path. This catches stale deployed code as well as logic bugs.

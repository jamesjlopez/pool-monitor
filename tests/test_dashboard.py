"""Regression checks for static dashboard interactions."""

from pathlib import Path


DASHBOARD = Path(__file__).parents[1] / "index.html"


def test_activity_history_controls_expand_and_restore_full_lists():
    """The dashboard's activity links must be wired to uncapped list rendering."""
    html = DASHBOARD.read_text()

    assert "function buildAlerts(notifications, limit = MAX_ALERTS)" in html
    assert "function buildIssues(errors, recalibrations, limit = MAX_ALERTS)" in html
    assert "return limit === null ? alerts : alerts.slice(0, limit);" in html
    assert "return limit === null ? issues : issues.slice(0, limit);" in html
    assert "document.getElementById('view-all-alerts').addEventListener('click'" in html
    assert "document.getElementById('view-full-log').addEventListener('click'" in html
    assert "renderActivityLists();" in html


def test_cleaning_forecast_is_mode_aware_and_resistant_to_spikes():
    """The dashboard must not project a cleaning from another program or retry burst."""
    html = DASHBOARD.read_text()

    assert "function forecastSamples(d)" in html
    assert "if (row.mode !== mode" in html
    assert "samples.length < 4" in html
    assert "function theilSen(xs, ys)" in html
    assert "const confirmed = isolated.slice(0, 3);" in html
    assert "const isolated = daily.filter" in html
    assert "Math.abs(next.pct - sample.pct) <= 15" in html
    assert "return { now, rows, labels" in html

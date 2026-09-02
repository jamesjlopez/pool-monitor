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


def test_duplicate_cloud_snapshots_are_excluded_from_chart_data():
    html = DASHBOARD.read_text()

    assert "r.telemetryQuality !== 'duplicate'" in html
    assert "telemetryQuality: o.telemetry_quality || 'legacy'" in html


def test_return_flow_reference_never_compares_legacy_rows_by_mode_alone():
    """Old rows lack program context, so their flow loss is unknowable."""
    html = DASHBOARD.read_text()

    assert "return null;" in html[html.index("function flowKey(r)"):html.index("function computeCleanFlowReferences(rows)")]
    assert "if (!key) return null;" in html[html.index("function flowReferenceForRow"):html.index("function buildRealData(days)")]


def test_only_manual_cleanings_create_filter_restriction_chart_markers():
    """Automatic signals are candidates, not confirmed cleaning events."""
    html = DASHBOARD.read_text()
    cleaning_builder = html[
        html.index("function buildCleanings()"):
        html.index("// ── Threshold lines plugin")
    ]

    assert "const auto" not in cleaning_builder
    assert "type:  'manual'" in cleaning_builder
    assert "return manual;" in cleaning_builder
    assert "Possible filter cleaning — unverified" in html


def test_chart_range_uses_latest_telemetry_instead_of_browser_clock():
    """A phone with an inaccurate clock must still show the available history."""
    html = DASHBOARD.read_text()
    data_builder = html[
        html.index("function buildRealData(days)"):
        html.index("// ── Build alert/issue arrays")
    ]

    assert "const now = new Date(freshRows[freshRows.length - 1].ts);" in data_builder
    assert "const cutoff = new Date(now);" in data_builder

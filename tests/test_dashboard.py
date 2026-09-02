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


def test_duplicate_cloud_snapshots_remain_visible_but_do_not_train_baselines():
    """A repeated cloud response is still an observed poll worth showing on the timeline."""
    html = DASHBOARD.read_text()

    data_builder = html[
        html.index("function buildRealData(days)"):
        html.index("// ── Build alert/issue arrays")
    ]
    assert "const now = new Date(allRows[allRows.length - 1].ts);" in data_builder
    assert "const rows = allRows.filter" in data_builder
    assert "freshRows.filter(r => new Date(r.ts) >= cutoff)" in data_builder
    assert "telemetryQuality: o.telemetry_quality || 'legacy'" in html


def test_return_flow_reference_never_compares_legacy_rows_by_mode_alone():
    """Old rows lack program context, so their flow loss is unknowable."""
    html = DASHBOARD.read_text()

    assert "return null;" in html[html.index("function flowKey(r)"):html.index("function computeCleanFlowReferences(rows)")]
    assert "if (!key) return null;" in html[html.index("function sessionReferenceForRow"):html.index("function buildRealData(days)")]


def test_derived_dashboard_metrics_require_verified_program_context():
    """Legacy raw flow may remain visible, but it must not train derived charts."""
    html = DASHBOARD.read_text()

    parser = html[html.index("function parseCSV(text)"):html.index("// ── Desktop alerts")]
    assert "trustedRows = freshRows.filter(hasVerifiedProgramContext);" in parser
    assert "computeCleanBaselines(trustedRows)" in parser


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

    assert "const now = new Date(allRows[allRows.length - 1].ts);" in data_builder
    assert "const cutoff = new Date(now);" in data_builder


def test_pressure_chart_uses_explicit_psi_telemetry_between_flow_and_restriction():
    """PSI is a direct gauge-comparison signal, never a reinterpretation of legacy raw data."""
    html = DASHBOARD.read_text()

    assert 'id="chart-flow"' in html
    assert 'id="chart-pressure"' in html
    assert 'id="chart-restriction"' in html
    assert html.index('id="chart-flow"') < html.index('id="chart-pressure"') < html.index('id="chart-restriction"')
    assert "pressurePsi: Number.isFinite(rawPressurePsi) ? rawPressurePsi : null," in html
    assert "const pressurePsi = rows.map(r => r.pressurePsi);" in html
    assert "charts.pressure = new Chart(document.getElementById('chart-pressure')" in html


def test_flow_and_pressure_clean_references_are_separated_by_verified_operating_session():
    """Low- and high-speed programs must never share a clean flow or PSI reference."""
    html = DASHBOARD.read_text()

    reference_builder = html[
        html.index("function flowKey(r)"):html.index("function buildRealData(days)")
    ]
    assert "function computeCleanSessionReferences(rows, valueForRow, percentile)" in reference_builder
    assert "return computeCleanSessionReferences(rows, r => r.pressurePsi, 0.10);" in reference_builder
    assert "const pressureReference = rows.map(r => sessionReferenceForRow(r, cleanPressureReferences));" in html
    assert "const pressureRise = pressurePsi.map((value, i) =>" in html
    assert "Number.isFinite(value) && Number.isFinite(pressureReference[i])" in html
    assert "data: d.pressureReference" in html
    assert "Clean PSI reference" in html


def test_logged_cleanings_mark_both_return_flow_and_pressure_charts():
    """The independent hydraulic charts share the same confirmed-cleaning timeline."""
    html = DASHBOARD.read_text()

    flow_chart = html[html.index("charts.flow = new Chart"):html.index("// Filter pressure")]
    pressure_chart = html[html.index("charts.pressure = new Chart"):html.index("// Pump workload")]
    assert "cleaningMarkersPlugin(allCleanings)" in flow_chart
    assert "cleaningMarkersPlugin(allCleanings)" in pressure_chart


def test_missing_or_malformed_psi_telemetry_is_a_chart_gap():
    """Older CSV headers and malformed PSI values must not leak NaN into chart data."""
    html = DASHBOARD.read_text()

    assert "const rawPressurePsi = +o.pressure_psi;" in html
    assert "pressurePsi: Number.isFinite(rawPressurePsi) ? rawPressurePsi : null," in html
    assert "Number.isFinite(latestPressure)" in html

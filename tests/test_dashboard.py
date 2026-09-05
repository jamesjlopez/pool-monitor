"""Regression checks for static dashboard interactions."""

import json
from pathlib import Path
import subprocess
import pytest


DASHBOARD = Path(__file__).parents[1] / "index.html"


def render_live_hero(html, csv_text, now):
    """Exercise the shipped parser, calculations and hero with a minimal DOM."""
    script = "\n".join([
        "const nodes = {}; const node = id => nodes[id] ||= {style: {setProperty() {}}};",
        "const document = {getElementById: node, querySelector: node, documentElement: node('root')};",
        "const C = {}; const STALE_MIN = 45, POLL_HRS = 0.5, KWH_RATE = 0.14;",
        "let allRows = [], freshRows = [], cleanBaselines = {}, cleanFlowReferences = {}, cleanPressureReferences = {};",
        "function relAge(ts) { return ts; } function predictClean() { return {none:true}; }",
        html[html.index("function latestFreshAlertLevel(rows)"):html.index("// ── Build alert/issue arrays")],
        html[html.index("function parseCSV(text)"):html.index("// ── Desktop alerts")],
        "let dashCfg = defaultDashboardConfig();",
        f"Date.now = () => {now};",
        f"parseCSV({json.dumps(csv_text)});",
        "setHeroFromData(buildRealData(7));",
        "console.log(JSON.stringify(nodes));",
    ])
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def hydraulic_csv(*versions):
    header = "timestamp,pressure_psi,power_watts,flow_gph,watts_per_gph,speed_mode,alert_level,active_program,active_reference,active_setpoint,telemetry_version"
    return header + "\n" + "\n".join(
        f"2026-09-05T11:{i*10:02d}:00,12,500,3000,0.1667,low,warn,low speed,3,705,{version}"
        for i, version in enumerate(versions)
    )


def test_recent_repeated_hydraulics_keep_values_and_warning_visible():
    source = 1788624474
    csv_text = hydraulic_csv(f"d|{source-3600}|w|{source-3600}",
                             f"d|{source}|w|{source}", f"d|{source}|w|{source}")
    nodes = render_live_hero(DASHBOARD.read_text(), csv_text, (source + 3000) * 1000)
    assert nodes["status-headline"]["textContent"] == "Pump pressure needs attention"
    assert nodes["st-pressure-now"]["innerHTML"] == "12.00<small> PSI</small>"
    assert nodes["st-flow-now"]["innerHTML"] == "50<small>GPM</small>"
    assert "readings " in nodes["hero-updated"]["textContent"]


def test_expired_source_is_stale_even_when_last_poll_advanced():
    source = 1788624474
    csv_text = hydraulic_csv(f"d|{source-3600}|w|{source-3600}", f"d|{source}|w|{source}")
    nodes = render_live_hero(DASHBOARD.read_text(), csv_text, (source + 5400) * 1000)
    assert nodes["status-headline"]["textContent"] == "Hydraulic readings are stale"
    assert nodes["st-pressure-now"]["innerHTML"] == "—"


def test_mixed_pressure_flow_update_does_not_reuse_last_pair():
    source = 1788624474
    csv_text = hydraulic_csv(f"d|{source-3600}|w|{source-3600}",
                             f"d|{source}|w|{source}", f"d|{source+60}|w|{source}")
    nodes = render_live_hero(DASHBOARD.read_text(), csv_text, (source + 3000) * 1000)
    assert nodes["st-pressure-now"]["innerHTML"] == "—"


@pytest.mark.parametrize("case", ["initial", "future", "changed_program", "expired_duplicate"])
def test_untrusted_or_expired_pairs_never_render_current_values(case):
    source = 1788624474
    versions = [f"d|{source-3600}|w|{source-3600}", f"d|{source}|w|{source}"]
    now = source + 3000
    if case == "initial":
        versions = versions[-1:]
    if case == "future":
        now = source - 1
    if case in {"changed_program", "expired_duplicate"}:
        versions.append(versions[-1])
    if case == "expired_duplicate":
        now = source + 5400
    csv_text = hydraulic_csv(*versions)
    if case == "changed_program":
        lines = csv_text.splitlines()
        lines[-1] = lines[-1].replace("low speed", "high speed")
        csv_text = "\n".join(lines)
    nodes = render_live_hero(DASHBOARD.read_text(), csv_text, now * 1000)
    assert nodes["st-pressure-now"]["innerHTML"] == "—"
    assert nodes["st-gpm"]["innerHTML"] == "—"


def test_dashboard_uses_configured_source_expiry():
    html = DASHBOARD.read_text()
    helpers = html[html.index("function defaultDashboardConfig()"):html.index("function speedCfg(mode)")]
    script = helpers + '\nconsole.log(parseDashboardConfig("telemetry_health:\\n  stale_alert_after_seconds: 7200\\n", defaultDashboardConfig()).staleAfterSeconds);'
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    assert result.stdout.strip() == "7200"


def test_restriction_uses_derived_clean_baseline_when_config_is_uncalibrated():
    """An uncalibrated config must not flatten the restriction chart at zero."""
    html = DASHBOARD.read_text()
    helpers = html[
        html.index("function speedCfg(mode)"):
        html.index("function computeCleanSessionReferences(rows, valueForRow, percentile)")
    ]
    rows = [
        {"gph": 1800, "ratio": 0.20, "mode": "low", "rowBaseline": None,
         "telemetryVersion": f"d|{n}|w|{n}"}
        for n in range(1, 6)
    ] + [{"gph": 1800, "ratio": 0.30, "mode": "low", "rowBaseline": None,
           "telemetryVersion": "d|6|w|6"}]
    script = "\n".join([
        "let dashCfg = {speeds: {low: {baseline: null, alertPct: 100, emergencyPct: 300}}};",
        helpers,
        f"const rows = {json.dumps(rows)};",
        "classifyHydraulicRows(rows);",
        "const baselines = computeCleanBaselines(rows);",
        "annotateRows(rows, baselines);",
        "console.log(JSON.stringify(rows.at(-1)));",
    ])

    result = subprocess.run(
        ["node", "-e", script], check=True, capture_output=True, text=True
    )
    assert json.loads(result.stdout)["pct"] == 50


def test_live_pressure_warning_overrides_a_low_restriction_hero_status():
    """Direct engine warnings must never be rendered as an all-clear state."""
    html = DASHBOARD.read_text()
    hero = html[html.index("function setHeroFromData(d)"):html.index("// ── Config loading")]

    assert "else if (liveLevel === 'warn')" in hero
    assert "Pump pressure needs attention" in hero
    assert hero.index("liveLevel === 'warn'") < hero.index("nowPct >= 100")


def test_hero_uses_last_fresh_alert_level_when_latest_snapshot_is_duplicate():
    """A duplicate cloud response must not clear a live pressure warning."""
    html = DASHBOARD.read_text()
    helper = html[
        html.index("function latestFreshAlertLevel(rows)"):
        html.index("function setHeroFromData(d)")
    ]
    script = "\n".join([
        helper,
        "const rows = [",
        "  { hydraulicQuality: 'verified', level: 'warn' },",
        "  { hydraulicQuality: 'mixed_or_stale', level: 'normal' },",
        "];",
        "console.log(latestFreshAlertLevel(rows));",
    ])

    result = subprocess.run(
        ["node", "-e", script], check=True, capture_output=True, text=True
    )
    assert result.stdout.strip() == "warn"


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
    assert "classifyHydraulicRows(allRows);" in parser
    assert "freshRows = allRows.filter(r => r.hydraulicQuality === 'verified');" in parser
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
    assert "const pressurePsi = rows.map(r => r.hydraulicQuality === 'verified' ? r.pressurePsi : null);" in html
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


def test_isolated_verified_hydraulic_readings_have_visible_markers():
    """A valid reading between stale gaps must not disappear from either chart."""
    html = DASHBOARD.read_text()

    flow_chart = html[html.index("charts.flow = new Chart"):html.index("// Filter pressure")]
    pressure_chart = html[html.index("charts.pressure = new Chart"):html.index("// Pump workload")]
    assert "pointRadius: ctx => ctx.raw == null ? 0 : 3" in flow_chart
    assert "pointRadius: ctx => ctx.raw == null ? 0 : 3" in pressure_chart


def test_missing_or_malformed_psi_telemetry_is_a_chart_gap():
    """Older CSV headers and malformed PSI values must not leak NaN into chart data."""
    html = DASHBOARD.read_text()

    assert "const rawPressurePsi = +o.pressure_psi;" in html
    assert "pressurePsi: Number.isFinite(rawPressurePsi) ? rawPressurePsi : null," in html
    assert "Number.isFinite(latestPressure)" in html

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
        html[html.index("function currentHydraulicIndex(rows"):html.index("// ── Build alert/issue arrays")],
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


def test_recent_repeated_hydraulics_keep_values_visible_without_a_reference():
    source = 1788624474
    csv_text = hydraulic_csv(f"d|{source-3600}|w|{source-3600}",
                             f"d|{source}|w|{source}", f"d|{source}|w|{source}")
    nodes = render_live_hero(DASHBOARD.read_text(), csv_text, (source + 3000) * 1000)
    assert nodes["status-headline"]["textContent"] == "Learning the clean return flow"
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
    assert nodes["st-flow-now"]["innerHTML"] == "—"


def test_dashboard_uses_configured_source_expiry():
    html = DASHBOARD.read_text()
    helpers = html[html.index("function defaultDashboardConfig()"):html.index("function speedCfg(mode)")]
    script = helpers + '\nconsole.log(parseDashboardConfig("telemetry_health:\\n  stale_alert_after_seconds: 7200\\n", defaultDashboardConfig()).staleAfterSeconds);'
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    assert result.stdout.strip() == "7200"


def flow_status_csv(flows, level="critical", duplicate=False):
    source = 1788620000
    header = hydraulic_csv().splitlines()[0]
    rows = []
    for i, flow in enumerate(flows):
        stamp = source + i * 600
        rows.append(f"2026-09-05T11:00:00,12,500,{flow},0.8,low,{level},low speed,3,705,d|{stamp}|w|{stamp}")
    if duplicate:
        rows.extend([rows[-1]] * 4)
    return header + "\n" + "\n".join(rows), (stamp + 60) * 1000


@pytest.mark.parametrize("flow,headline", [
    (3000, "Return flow is healthy"),
    (2550, "Return flow is dropping"),
    (2250, "Check for a flow restriction"),
    (1800, "Return flow is very low"),
])
def test_hero_uses_confirmed_return_flow_loss_not_legacy_alerts(flow, headline):
    csv, now = flow_status_csv([3000] * 7 + [flow] * 3)
    nodes = render_live_hero(DASHBOARD.read_text(), csv, now)
    assert nodes["status-headline"]["textContent"] == headline
    assert "restriction" not in nodes["status-detail"]["textContent"].lower()
    assert "25%" in nodes["#hero-forecast .hf-text"]["textContent"]


def test_duplicate_flow_polls_do_not_confirm_a_cleaning():
    csv, now = flow_status_csv([3000] * 7 + [2100], duplicate=True)
    nodes = render_live_hero(DASHBOARD.read_text(), csv, now)
    assert nodes["status-headline"]["textContent"] == "Confirming reduced return flow"


def test_cleaning_confirmation_resets_after_long_source_gap():
    csv, now = flow_status_csv([3000] * 7 + [2100] * 3)
    lines = csv.splitlines()
    latest = lines[-1].split(',')
    stamp = int(latest[-1].split('|')[1]) + 72 * 3600
    latest[-1] = f'd|{stamp}|w|{stamp}'
    lines[-1] = ','.join(latest)
    nodes = render_live_hero(DASHBOARD.read_text(), '\n'.join(lines), (stamp + 60) * 1000)
    assert nodes['status-headline']['textContent'] == 'Confirming reduced return flow'


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


def test_duplicate_cloud_snapshots_remain_visible_but_do_not_train_baselines():
    """A repeated cloud response is still an observed poll worth showing on the timeline."""
    html = DASHBOARD.read_text()

    data_builder = html[
        html.index("function buildRealData(days)"):
        html.index("// ── Build alert/issue arrays")
    ]
    assert "const now = new Date(allRows[allRows.length - 1].ts);" in data_builder
    assert "const rows = allRows.filter" in data_builder
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
    assert "computeCleanFlowReferences(trustedRows)" in parser


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
    assert 'id="chart-restriction"' not in html
    assert 'id="chart-energy"' not in html
    assert 'id="chart-power"' not in html
    assert html.index('id="chart-flow"') < html.index('id="chart-pressure"')
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
    pressure_chart = html[html.index("charts.pressure = new Chart"):html.index("// ── Legend HTML")]
    assert "cleaningMarkersPlugin(allCleanings)" in flow_chart
    assert "cleaningMarkersPlugin(allCleanings)" in pressure_chart


def test_isolated_verified_hydraulic_readings_have_visible_markers():
    """A valid reading between stale gaps must not disappear from either chart."""
    html = DASHBOARD.read_text()

    flow_chart = html[html.index("charts.flow = new Chart"):html.index("// Filter pressure")]
    pressure_chart = html[html.index("charts.pressure = new Chart"):html.index("// ── Legend HTML")]
    assert "pointRadius: ctx => ctx.raw == null ? 0 : 3" in flow_chart
    assert "pointRadius: ctx => ctx.raw == null ? 0 : 3" in pressure_chart


def test_missing_or_malformed_psi_telemetry_is_a_chart_gap():
    """Older CSV headers and malformed PSI values must not leak NaN into chart data."""
    html = DASHBOARD.read_text()

    assert "const rawPressurePsi = +o.pressure_psi;" in html
    assert "pressurePsi: Number.isFinite(rawPressurePsi) ? rawPressurePsi : null," in html
    assert "Number.isFinite(latestPressure)" in html


@pytest.mark.parametrize('value,headline', [('', 'Learning the clean return flow'), ('0', 'Return flow is very low')])
def test_missing_flow_is_unknown_but_measured_zero_flow_is_severe(value, headline):
    csv, now = flow_status_csv([3000] * 7 + [0] * 3)
    if value == '':
        csv = csv.replace(',0,0.8,', ',,0.8,')
    nodes = render_live_hero(DASHBOARD.read_text(), csv, now)
    assert nodes['status-headline']['textContent'] == headline


def test_pump_off_without_legacy_ratio_is_not_a_cleaning_alert():
    csv, now = flow_status_csv([3000] * 7 + [0])
    csv = csv.replace(',500,0,0.8,', ',0,0,,')
    nodes = render_live_hero(DASHBOARD.read_text(), csv, now)
    assert nodes['status-headline']['textContent'] == 'Pump is off'
    assert nodes['hero-flow-loss']['textContent'] == '—'


def test_flow_confirmation_preserves_same_program_history_across_schedule_changes():
    csv, now = flow_status_csv([3000] * 7 + [2100] * 3)
    lines = csv.splitlines()
    lines[-2] = lines[-2].replace('low speed', 'high speed')
    nodes = render_live_hero(DASHBOARD.read_text(), '\n'.join(lines), now)
    assert nodes['status-headline']['textContent'] == 'Check for a flow restriction'


def test_return_flow_config_is_adjustable_and_invalid_thresholds_fall_back():
    html = DASHBOARD.read_text()
    helpers = html[html.index('function defaultDashboardConfig()'):html.index('function speedCfg(mode)')]
    script = helpers + '''
const good = parseDashboardConfig('dashboard_return_flow:\\n  watch_loss_pct: 10\\n  clean_loss_pct: 20\\n  inspect_loss_pct: 35\\n  consecutive_readings_required: 4', defaultDashboardConfig());
const bad = parseDashboardConfig('dashboard_return_flow:\\n  clean_loss_pct: 10', defaultDashboardConfig());
console.log(JSON.stringify([good.returnFlow, bad.returnFlow]));
'''
    result = subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)
    good, bad = json.loads(result.stdout)
    assert good == dict(watchPct=10, cleanPct=20, inspectPct=35, confirmations=4)
    assert bad == dict(watchPct=15, cleanPct=25, inspectPct=40, confirmations=2)


def test_page_refresh_detects_updates_and_preserves_open_cleaning_form():
    html = DASHBOARD.read_text()
    code = html[html.index('let refreshInFlight = false;'):html.index('// ── Boot')]
    script = '''
let served = '<html data-dashboard-version="v1">A</html>';
let reloads = 0, refreshes = 0;
const form = {hidden: true};
const document = {documentElement:{dataset:{dashboardVersion:'v1'}}, getElementById:()=>form, addEventListener(){}};
const location = {pathname:'/', reload(){reloads++;}};
const fetch = async()=>({ok:true,text:async()=>served});
const init = async()=>{refreshes++;};
const setInterval = ()=>{}; const REFRESH_MS = 300000;
''' + code + '''
(async()=>{
 await refreshDashboard();
 form.hidden=false;
 served='<html data-dashboard-version="v1">B</html>';
 await refreshDashboard();
 if(reloads!==0) throw Error('Lost unsaved cleaning form');
 form.hidden=true;
 await refreshDashboard();
 console.log(JSON.stringify({reloads,refreshes}));
})();
'''
    result = subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)
    assert json.loads(result.stdout) == {'reloads':1,'refreshes':2}


def test_dashboard_and_phone_share_confirmed_flow_levels():
    from monitor.return_flow import evaluate_flow
    import csv as csv_module
    import io
    for flow, level, headline in [(2550,1,'Return flow is dropping'),
                                   (2250,2,'Check for a flow restriction'),
                                   (1800,3,'Return flow is very low')]:
        data, now = flow_status_csv([3000]*7+[flow]*2)
        rows = list(csv_module.DictReader(io.StringIO(data)))
        result = evaluate_flow(rows, {}, now/1000)
        nodes = render_live_hero(DASHBOARD.read_text(),data,now)
        assert result['level'] == level
        assert nodes['status-headline']['textContent'] == headline


def test_maintenance_failed_save_keeps_form_and_retry_id():
    html = DASHBOARD.read_text()
    wiring = html[html.index('function wireCleaningForm()'):html.index('// ── Interactions')]
    script = r'''
const nodes = {};
const document = {getElementById(id) { return nodes[id] ||= {
  style: {}, hidden: true, value: '', focus() {},
  addEventListener(name, callback) {this[name] = callback;}
};}};
const crypto = {randomUUID() {return 'stable-id';}};
let allCleanings;
let attempts = [];
async function saveManualCleaning(ts, kind, notes, id) {
  attempts.push({ts, kind, notes, id});
  if (attempts.length === 1) throw new Error('unavailable');
}
function buildCleanings() {return [];}
function renderActivityLists() {}
function renderFromData() {}
''' + wiring + r'''
(async () => {
 wireCleaningForm();
 nodes['log-cleaning-open'].click();
 const initial = nodes['cleaning-dt'].value;
 nodes['cleaning-dt'].value = '2026-09-20T12:07';
 nodes['cleaning-kind'] = {value:'surface_skimmer'};
 nodes['cleaning-notes'].value = 'leaves';
 await nodes['cleaning-save'].click();
 if (nodes['cleaning-form'].hidden || nodes['cleaning-save'].disabled) throw Error('lost retry');
 await nodes['cleaning-save'].click();
 if (!nodes['cleaning-form'].hidden || attempts[0].id !== attempts[1].id) throw Error('bad retry');
 if (attempts[0].ts !== '2026-09-20T17:07:00.000Z') throw Error('wrong timezone');
 console.log('ok');
})();
'''
    import os
    result = subprocess.run(['node', '-e', script], check=True, capture_output=True,
                            text=True, env={**os.environ, 'TZ': 'America/Chicago'})
    assert result.stdout.strip() == 'ok'

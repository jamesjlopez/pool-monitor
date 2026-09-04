import csv

from monitor.hydraulic_quality import classify_hydraulic_rows, write_hydraulic_audit


def row(timestamp, pressure, flow):
    return {
        "timestamp": timestamp,
        "telemetry_version": f"device|{pressure}|watts|{flow}",
    }


def test_only_paired_advances_are_verified_for_analytics():
    audit = classify_hydraulic_rows([
        row("08:00", 100, 100),
        row("08:15", 110, 100),  # power/device may be new, but flow is stale
        row("08:30", 120, 120),
        {"timestamp": "08:45", "telemetry_version": ""},
    ])

    assert [item["hydraulic_quality"] for item in audit] == [
        "initial", "mixed_or_stale", "verified", "unverifiable",
    ]


def test_audit_is_a_sidecar_and_never_rewrites_metrics_source(tmp_path):
    metrics = tmp_path / "metrics.csv"
    source = "timestamp,telemetry_version\n08:00,device|100|watts|100\n08:15,device|110|watts|110\n"
    metrics.write_text(source)

    audit = write_hydraulic_audit(metrics)

    assert metrics.read_text() == source
    with open(audit, newline="") as f:
        assert [row["hydraulic_quality"] for row in csv.DictReader(f)] == ["initial", "verified"]

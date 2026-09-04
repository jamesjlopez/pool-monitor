"""Classify whether logged pressure and flow came from a paired cloud update.

``metrics.csv`` remains the immutable source record.  This module writes a
sidecar audit instead of rewriting or deleting historical observations.
"""

import csv
from pathlib import Path


AUDIT_COLUMNS = ["timestamp", "hydraulic_quality", "reason"]


def classify_hydraulic_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Return a strict, chronological paired-update classification for *rows*.

    A verified row must advance both the pressure (s17) and flow (s26) source
    timestamps from the last verified pair.  The initial pair has no preceding
    observation to verify against, and is intentionally excluded from analytics.
    """
    accepted_pressure: int | None = None
    accepted_flow: int | None = None
    audit: list[dict[str, str]] = []

    for row in rows:
        parts = row.get("telemetry_version", "").split("|")
        quality = "unverifiable"
        reason = "missing or malformed per-field source timestamps"
        try:
            pressure, flow = int(parts[1]), int(parts[3])
        except (IndexError, ValueError):
            pass
        else:
            if accepted_pressure is None:
                accepted_pressure, accepted_flow = pressure, flow
                quality = "initial"
                reason = "first paired source timestamps in retained history"
            elif pressure > accepted_pressure and flow > accepted_flow:
                accepted_pressure, accepted_flow = pressure, flow
                quality = "verified"
                reason = "pressure and flow source timestamps both advanced"
            else:
                quality = "mixed_or_stale"
                reason = "pressure and flow source timestamps did not both advance"
        audit.append({
            "timestamp": row.get("timestamp", ""),
            "hydraulic_quality": quality,
            "reason": reason,
        })
    return audit


def write_hydraulic_audit(metrics_path: Path) -> Path:
    """Create/update the non-destructive audit sidecar for a metrics CSV."""
    audit_path = metrics_path.with_name("hydraulic-audit.csv")
    with open(metrics_path, newline="") as source:
        audit = classify_hydraulic_rows(list(csv.DictReader(source)))
    with open(audit_path, "w", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=AUDIT_COLUMNS)
        writer.writeheader()
        writer.writerows(audit)
    return audit_path

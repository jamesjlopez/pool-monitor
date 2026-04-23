#!/usr/bin/env python3
"""
extractor_template.py
Extract PSI/GPH/Power metrics from pool pump screenshot images using vision,
then output a calibration dataset correlating PSI with watts/GPH ratio.

Usage:
    python analysis/extractor_template.py              # process data/screenshots/
    python analysis/extractor_template.py /path/dir    # process a specific directory
    python analysis/extractor_template.py --calibrate  # compute baseline ratios from extracted data

Drop screenshots into data/screenshots/ before running.
Annotated screenshots (with PSI written on them) give the most accurate calibration.
"""

import argparse
import base64
import csv
import json
import sys
from pathlib import Path

SCREENSHOTS_DIR = Path(__file__).parent.parent / "data" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR = Path(__file__).parent.parent / "data"

PROMPT = """You are analyzing a screenshot from a Pentair pool pump controller app (Pentair Home).
Extract ALL of the following numeric values if visible:
- PSI (filter pressure, in pounds per square inch — may be handwritten on the image)
- GPH (flow rate, in gallons per hour — may appear as "Flow" or "GPH")
- Power (wattage — may appear as "Watts", "W", or "Power"; convert kW to W)
- RPM (pump speed in rotations per minute — may appear as "Speed" or "RPM")

Return ONLY valid JSON in this exact format (use null for any value not found):
{"psi": <number|null>, "gph": <number|null>, "power_watts": <number|null>, "rpm": <number|null>}
"""


def encode_image(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode()


def extract_with_ollama(image_path: Path, model: str = "gemma4:26b-a4b-it-q4_K_M") -> dict:
    import urllib.request
    payload = {
        "model": model,
        "prompt": PROMPT,
        "images": [encode_image(image_path)],
        "stream": False,
        "format": "json",
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())
    return json.loads(result.get("response", "{}"))


def process_screenshots(directory: Path = SCREENSHOTS_DIR) -> list[dict]:
    """Extract metrics from all screenshots in directory. Returns list of metric dicts."""
    images = sorted(directory.glob("*.png")) + sorted(directory.glob("*.jpg")) + sorted(directory.glob("*.jpeg"))
    if not images:
        print(f"No screenshots found in {directory}")
        print("Drop .png or .jpg files there and re-run.")
        return []

    results = []
    for img in images:
        print(f"Processing {img.name}...")
        try:
            metrics = extract_with_ollama(img)
            metrics["source"] = img.name
            results.append(metrics)
            print(
                f"  PSI={metrics.get('psi')}  GPH={metrics.get('gph')}  "
                f"W={metrics.get('power_watts')}  RPM={metrics.get('rpm')}"
            )
        except Exception as e:
            print(f"  ERROR: {e}")

    out_path = DATA_DIR / "extracted_metrics.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved {len(results)} results to {out_path}")
    return results


def compute_calibration(metrics: list[dict]) -> dict:
    """
    Compute baseline watts/GPH ratios from extracted metrics for each speed mode.
    Filters to only readings with PSI in the 'clean' range (≤ 10 PSI).
    Outputs data/calibration_dataset.csv and data/psi_model.json.
    """
    rows = []
    for m in metrics:
        psi = m.get("psi")
        gph = m.get("gph")
        watts = m.get("power_watts")
        rpm = m.get("rpm")

        # Skip incomplete rows
        if any(v is None for v in [gph, watts]):
            continue
        if gph <= 0:
            continue

        ratio = watts / gph
        speed_mode = "low" if (rpm is None or rpm < 1500) else "high"

        rows.append({
            "source": m.get("source", ""),
            "psi": psi,
            "rpm": rpm,
            "power_watts": watts,
            "flow_gph": gph,
            "watts_per_gph": round(ratio, 5),
            "speed_mode": speed_mode,
        })

    # Write CSV for inspection
    csv_path = DATA_DIR / "calibration_dataset.csv"
    if rows:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nCalibration dataset: {csv_path} ({len(rows)} rows)")

    # Compute baseline ratios from clean-filter readings (PSI ≤ 10)
    clean_low = [r for r in rows if r["speed_mode"] == "low" and r["psi"] is not None and r["psi"] <= 10]
    clean_high = [r for r in rows if r["speed_mode"] == "high" and r["psi"] is not None and r["psi"] <= 15]

    def avg(lst, key):
        vals = [x[key] for x in lst if x[key] is not None]
        return round(sum(vals) / len(vals), 5) if vals else None

    model = {
        "note": "Baseline watts/GPH ratios on clean filter — paste into config.yaml",
        "low_speed": {
            "baseline_watts_per_gph": avg(clean_low, "watts_per_gph"),
            "sample_count": len(clean_low),
            "avg_clean_psi": avg(clean_low, "psi"),
        },
        "high_speed": {
            "baseline_watts_per_gph": avg(clean_high, "watts_per_gph"),
            "sample_count": len(clean_high),
            "avg_clean_psi": avg(clean_high, "psi"),
        },
    }

    model_path = DATA_DIR / "psi_model.json"
    with open(model_path, "w") as f:
        json.dump(model, f, indent=2)

    print(f"\nPSI model saved to {model_path}")
    print(json.dumps(model, indent=2))
    print("\nTo use these baselines, update config.yaml:")
    if model["low_speed"]["baseline_watts_per_gph"]:
        print(f"  thresholds.low_speed.baseline_watts_per_gph: {model['low_speed']['baseline_watts_per_gph']}")
    if model["high_speed"]["baseline_watts_per_gph"]:
        print(f"  thresholds.high_speed.baseline_watts_per_gph: {model['high_speed']['baseline_watts_per_gph']}")

    return model


def main():
    parser = argparse.ArgumentParser(description="Extract pump metrics from screenshots")
    parser.add_argument("directory", nargs="?", type=Path, default=SCREENSHOTS_DIR)
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Re-run calibration on already-extracted data/extracted_metrics.json",
    )
    args = parser.parse_args()

    if args.calibrate:
        metrics_path = DATA_DIR / "extracted_metrics.json"
        if not metrics_path.exists():
            print(f"No extracted_metrics.json found. Run without --calibrate first.")
            sys.exit(1)
        with open(metrics_path) as f:
            metrics = json.load(f)
        compute_calibration(metrics)
    else:
        metrics = process_screenshots(args.directory)
        if metrics:
            compute_calibration(metrics)


if __name__ == "__main__":
    main()

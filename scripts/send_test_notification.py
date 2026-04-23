#!/usr/bin/env python3
"""Quick smoke test — sends a test notification to confirm ntfy is working."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from monitor.notifier import NtfyNotifier

config_path = Path(__file__).parent.parent / "config.yaml"
with open(config_path) as f:
    config = yaml.safe_load(f)

notifier = NtfyNotifier(config)
ok = notifier.send_test()

if ok:
    print("✓ Test notification sent successfully.")
    print(f"  Check your phone for a notification on topic: {config['ntfy']['topic']}")
else:
    print("✗ Failed to send notification. Check logs and ntfy config.")
    sys.exit(1)

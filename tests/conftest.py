"""Shared test safeguards for the Pool Monitor suite."""

import pytest

from monitor import runner


@pytest.fixture(autouse=True)
def isolate_runner_runtime_files(tmp_path, monkeypatch):
    """Keep test alerts, errors, and state out of the live dashboard logs."""
    runtime_logs = tmp_path / "logs"
    monkeypatch.setattr(runner, "NOTIFICATIONS_FILE", runtime_logs / "notifications.json")
    monkeypatch.setattr(runner, "ERRORS_FILE", runtime_logs / "errors.json")
    monkeypatch.setattr(runner, "STATE_FILE", runtime_logs / "state.json")
    monkeypatch.setattr(runner, "RECAL_LOG_FILE", runtime_logs / "recalibrations.json")

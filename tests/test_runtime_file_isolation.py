"""Guard against tests polluting the dashboard's live activity feeds."""

from monitor import runner


def test_runner_runtime_files_are_not_the_live_dashboard_files():
    live_logs = runner.PROJECT_ROOT / "logs"

    assert runner.NOTIFICATIONS_FILE.parent != live_logs
    assert runner.ERRORS_FILE.parent != live_logs
    assert runner.STATE_FILE.parent != live_logs

"""Tests for monitor/notifier.py — ntfy integration and alert deduplication."""

import time

import pytest
import requests

from monitor.notifier import NtfyNotifier
from monitor.types import AlertLevel


BASE_CONFIG = {
    "ntfy": {
        "server": "https://ntfy.sh",
        "topic": "test_pool_monitor",
        "priority_alert": "high",
        "priority_emergency": "urgent",
    },
    "thresholds": {
        "alert_cooldown_minutes": 30,
    },
}


class TestSendAlert:
    def test_normal_level_never_sends(self, mocker):
        mock_post = mocker.patch("monitor.notifier.requests.post")
        n = NtfyNotifier(BASE_CONFIG)
        result = n.send_alert(AlertLevel.NORMAL, "all good", "status")
        assert result is False
        mock_post.assert_not_called()

    def test_warn_sends_successfully(self, mocker):
        mock_resp = mocker.MagicMock()
        mock_resp.raise_for_status.return_value = None
        mocker.patch("monitor.notifier.requests.post", return_value=mock_resp)

        n = NtfyNotifier(BASE_CONFIG)
        result = n.send_alert(AlertLevel.WARN, "Filter dirty", "RPM: 1050")
        assert result is True

    def test_critical_sends_with_urgent_priority(self, mocker):
        mock_resp = mocker.MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_post = mocker.patch("monitor.notifier.requests.post", return_value=mock_resp)

        n = NtfyNotifier(BASE_CONFIG)
        n.send_alert(AlertLevel.CRITICAL, "Extreme pressure", "RPM: 2800")

        call_kwargs = mock_post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers.get("Priority") == "urgent"

    def test_warn_uses_high_priority(self, mocker):
        mock_resp = mocker.MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_post = mocker.patch("monitor.notifier.requests.post", return_value=mock_resp)

        n = NtfyNotifier(BASE_CONFIG)
        n.send_alert(AlertLevel.WARN, "Filter dirty", "status")

        call_kwargs = mock_post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers.get("Priority") == "high"

    def test_network_failure_returns_false(self, mocker):
        mocker.patch(
            "monitor.notifier.requests.post",
            side_effect=requests.RequestException("timeout"),
        )
        n = NtfyNotifier(BASE_CONFIG)
        result = n.send_alert(AlertLevel.WARN, "Filter dirty", "status")
        assert result is False


class TestCooldown:
    def test_warn_suppressed_within_cooldown(self, mocker):
        mock_resp = mocker.MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_post = mocker.patch("monitor.notifier.requests.post", return_value=mock_resp)

        n = NtfyNotifier(BASE_CONFIG)
        n.send_alert(AlertLevel.WARN, "First alert", "status")
        result = n.send_alert(AlertLevel.WARN, "Second alert", "status")

        assert result is False
        assert mock_post.call_count == 1  # second was suppressed

    def test_critical_ignores_cooldown(self, mocker):
        mock_resp = mocker.MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_post = mocker.patch("monitor.notifier.requests.post", return_value=mock_resp)

        n = NtfyNotifier(BASE_CONFIG)
        n.send_alert(AlertLevel.CRITICAL, "First critical", "status")
        result = n.send_alert(AlertLevel.CRITICAL, "Second critical", "status")

        assert result is True
        assert mock_post.call_count == 2  # both sent

    def test_cooldown_expires_after_window(self, mocker):
        mock_resp = mocker.MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_post = mocker.patch("monitor.notifier.requests.post", return_value=mock_resp)

        # Zero-cooldown config
        config = {**BASE_CONFIG, "thresholds": {"alert_cooldown_minutes": 0}}
        n = NtfyNotifier(config)
        n.send_alert(AlertLevel.WARN, "First", "status")
        result = n.send_alert(AlertLevel.WARN, "Second", "status")

        assert result is True
        assert mock_post.call_count == 2

    def test_different_levels_have_independent_cooldowns(self, mocker):
        mock_resp = mocker.MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_post = mocker.patch("monitor.notifier.requests.post", return_value=mock_resp)

        n = NtfyNotifier(BASE_CONFIG)
        n.send_alert(AlertLevel.WARN, "warn", "status")
        # CRITICAL has its own cooldown tracker — should still send
        result = n.send_alert(AlertLevel.CRITICAL, "critical", "status")
        assert result is True

    def test_cooldown_remaining_before_send_is_none(self):
        n = NtfyNotifier(BASE_CONFIG)
        assert n.cooldown_remaining(AlertLevel.WARN) is None

    def test_cooldown_remaining_after_send_is_positive(self, mocker):
        mock_resp = mocker.MagicMock()
        mock_resp.raise_for_status.return_value = None
        mocker.patch("monitor.notifier.requests.post", return_value=mock_resp)

        n = NtfyNotifier(BASE_CONFIG)
        n.send_alert(AlertLevel.WARN, "alert", "status")
        remaining = n.cooldown_remaining(AlertLevel.WARN)
        assert remaining is not None
        assert remaining > 0

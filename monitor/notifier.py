#!/usr/bin/env python3
"""
Notifier — sends push notifications via ntfy.sh.
Includes alert deduplication: same level won't re-fire within cooldown_minutes.
CRITICAL alerts always fire (no cooldown suppression).
"""

import logging
import os
import time
from typing import Optional

import requests

from .types import AlertLevel

log = logging.getLogger(__name__)


class NtfyNotifier:
    def __init__(self, config: dict):
        ntfy = config["ntfy"]
        self._server = ntfy["server"].rstrip("/")
        self._topic = os.environ.get("NTFY_TOPIC") or ntfy["topic"]
        self._priority_alert = ntfy.get("priority_alert", "high")
        self._priority_emergency = ntfy.get("priority_emergency", "urgent")
        self._cooldown_seconds = config["thresholds"].get("alert_cooldown_minutes", 30) * 60
        self._last_sent: dict[AlertLevel, float] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_alert(self, level: AlertLevel, reason: str, status_summary: str) -> bool:
        """
        Send a notification. Returns True if sent, False if suppressed or failed.
        CRITICAL always sends. WARN respects cooldown.
        """
        if level == AlertLevel.NORMAL:
            return False

        if level != AlertLevel.CRITICAL and self._is_cooling_down(level):
            log.debug("Alert %s suppressed (cooldown active)", level)
            return False

        title, message, priority, tags = self._format(level, reason, status_summary)
        sent = self._post(title, message, priority, tags)
        if sent:
            self._last_sent[level] = time.time()
        return sent

    def send_test(self) -> bool:
        """Send a test notification to confirm ntfy is working."""
        return self._post(
            title="Pool Monitor - Test",
            message="Notification system is working. Pool monitor is active.",
            priority="default",
            tags=["white_check_mark"],
        )

    def cooldown_remaining(self, level: AlertLevel) -> Optional[float]:
        """Seconds until this level can alert again, or None if not cooling down."""
        last = self._last_sent.get(level)
        if last is None:
            return None
        remaining = self._cooldown_seconds - (time.time() - last)
        return remaining if remaining > 0 else None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _is_cooling_down(self, level: AlertLevel) -> bool:
        return self.cooldown_remaining(level) is not None

    def _format(
        self, level: AlertLevel, reason: str, status_summary: str
    ) -> tuple[str, str, str, list[str]]:
        if level == AlertLevel.CRITICAL:
            return (
                "Pool Pump EMERGENCY",
                f"\U0001f6a8 {reason}\n\n{status_summary}",
                self._priority_emergency,
                ["rotating_light", "no_entry"],
            )
        return (
            "Pool Filter Alert",
            f"\u26a0\ufe0f {reason}\n\n{status_summary}\n\nCheck and rinse filter.",
            self._priority_alert,
            ["warning"],
        )

    def _post(self, title: str, message: str, priority: str, tags: list[str]) -> bool:
        url = f"{self._server}/{self._topic}"
        # Headers must be ASCII; encode non-ASCII chars as XML entities
        def ascii_safe(s: str) -> str:
            return s.encode("ascii", errors="xmlcharrefreplace").decode("ascii")
        try:
            resp = requests.post(
                url,
                data=message.encode("utf-8"),
                headers={
                    "Title": ascii_safe(title),
                    "Priority": priority,
                    "Tags": ",".join(tags),
                    "Content-Type": "text/plain; charset=utf-8",
                },
                timeout=10,
            )
            resp.raise_for_status()
            log.info("ntfy sent: [%s] %s", priority, title)
            return True
        except requests.RequestException as e:
            log.error("ntfy failed: %s", e)
            return False

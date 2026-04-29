#!/usr/bin/env python3
"""
Pentair Cloud API Client

Authenticates with Pentair's AWS Cognito service and polls the Pentair cloud API
for live pump telemetry (RPM, watts, flow GPH).

Field mapping (reverse-engineered from API response):
  s3   = running state (1 = on)
  s14  = active program index, 0-based (0 = zp1, 1 = zp2 "Low speed", 2 = zp3 "High speed")
  s16  = active setpoint value (unit depends on s15 reference type)
  s17  = actual RPM
  s18  = actual power (watts)
  s19  = current motor speed (tenths %) — NOT flow; 705 = 70.5% speed
  s26  = current estimated flow (tenths GPM) — 139 = 13.9 GPM; fluctuates under load

Control fields (writable via PUT):
  d25          = master Pump Status switch (1 = enabled, 0 = disabled — prevents scheduled restarts)
  zp{n}e10     = program run state (2 = stop current run, 3 = run immediately)
  appuse       = read-only reflection of d25 state, do not write

Speed mode is derived from active program name (zp{n}e2 field):
  contains "low"  → "low"
  contains "high" → "high"
  fallback        → RPM < 1500 → "low", else "high"

This pump runs in flow-control mode: it adjusts RPM automatically to maintain
target GPH. Clogging detection works by watching watts rise above a clean-filter
baseline while flow holds steady.

For testing without a live pump, use MockPentairClient.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import boto3
import requests
from pycognito import Cognito
from requests_aws4auth import AWS4Auth

from .types import PumpStatus

log = logging.getLogger(__name__)

# Pentair AWS infrastructure (from community reverse-engineering of Pentair Home app)
_AWS_REGION           = "us-west-2"
_USER_POOL_ID         = "us-west-2_lbiduhSwD"
_CLIENT_ID            = "3de110o697faq7avdchtf07h4v"
_IDENTITY_POOL_ID     = "us-west-2:6f950f85-af44-43d9-b690-a431f753e9aa"
_COGNITO_ENDPOINT     = "cognito-idp.us-west-2.amazonaws.com"

_BASE_URL             = "https://api.pentair.cloud"
_DEVICES_PATH         = "/device/device-service/user/devices"
_DEVICE_STATUS_PATH   = "/device2/device2-service/user/device"
_DEVICE_CONTROL_PATH  = "/device/device-service/user/device/"

# AWS temporary credentials expire after ~1 hour; refresh proactively
_CRED_TTL_SECONDS = 3000


class PentairCloudClient:
    """
    Live client for Pentair IntelliConnect / IntelliFlo VSF via Pentair cloud API.
    Credentials (email + password) are read from config or environment variables:
      PENTAIR_EMAIL, PENTAIR_PASSWORD
    """

    def __init__(self, config: dict):
        pcfg = config.get("pentair", {})
        self._email    = os.environ.get("PENTAIR_EMAIL")    or pcfg.get("email", "")
        self._password = os.environ.get("PENTAIR_PASSWORD") or pcfg.get("password", "")
        if not self._email or not self._password:
            raise ValueError(
                "Pentair credentials not set. Add pentair.email / pentair.password "
                "to config.yaml or set PENTAIR_EMAIL / PENTAIR_PASSWORD env vars."
            )
        self._cognito:       Optional[Cognito]  = None
        self._id_token:      Optional[str]      = None
        self._access_key:    Optional[str]      = None
        self._secret_key:    Optional[str]      = None
        self._session_token: Optional[str]      = None
        self._cred_expiry:   float              = 0.0
        self._device_id:     Optional[str]      = None
        self._authenticate()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_status(self) -> Optional[PumpStatus]:
        """Fetch current pump telemetry. Returns None on any error."""
        try:
            self._refresh_if_needed()
            if not self._device_id:
                self._discover_device()
            if not self._device_id:
                log.error("No Pentair device found in account")
                return None
            return self._fetch_status()
        except Exception as e:
            log.error("get_status failed: %s", e)
            return None

    def set_speed_program(self, program_index: int) -> bool:
        """Activate a pump program by 1-based program number (e.g. 2 = Low speed)."""
        try:
            self._refresh_if_needed()
            payload = json.dumps({"payload": {f"zp{program_index}e10": "3"}})
            r = requests.put(
                _BASE_URL + _DEVICE_CONTROL_PATH + self._device_id,
                auth=self._aws_auth(),
                headers=self._headers(),
                data=payload,
                timeout=15,
            )
            r.raise_for_status()
            result = r.json()
            return result.get("data", {}).get("code") == "set_device_success"
        except Exception as e:
            log.error("set_speed_program failed: %s", e)
            return False

    def turn_off(self) -> bool:
        """Stop the currently running program."""
        try:
            self._refresh_if_needed()
            # Find the active program and stop it
            status_raw = self._raw_status()
            if not status_raw:
                return False
            fields = status_raw.get("fields", {})
            active_idx = int(fields.get("s14", {}).get("value", 0)) + 1
            payload = json.dumps({"payload": {f"zp{active_idx}e10": "2"}})
            r = requests.put(
                _BASE_URL + _DEVICE_CONTROL_PATH + self._device_id,
                auth=self._aws_auth(),
                headers=self._headers(),
                data=payload,
                timeout=15,
            )
            r.raise_for_status()
            result = r.json()
            ok = result.get("data", {}).get("code") == "set_device_success"
            if ok:
                log.warning("Pump stopped via API")
            return ok
        except Exception as e:
            log.error("turn_off failed: %s", e)
            return False

    def set_pump_enabled(self, enabled: bool) -> bool:
        """
        Flip the master Pump Status toggle (appuse field).
        enabled=False turns off the switch and prevents scheduled restarts.
        """
        try:
            self._refresh_if_needed()
            payload = json.dumps({"payload": {"d25": "1" if enabled else "0"}})
            r = requests.put(
                _BASE_URL + _DEVICE_CONTROL_PATH + self._device_id,
                auth=self._aws_auth(),
                headers=self._headers(),
                data=payload,
                timeout=15,
            )
            r.raise_for_status()
            ok = r.json().get("data", {}).get("code") == "set_device_success"
            if ok:
                log.warning("Pump Status switch set to %s via API", "ON" if enabled else "OFF")
            return ok
        except Exception as e:
            log.error("set_pump_enabled failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _authenticate(self):
        log.info("Authenticating with Pentair cloud...")
        self._cognito = Cognito(_USER_POOL_ID, _CLIENT_ID, username=self._email)
        self._cognito.authenticate(password=self._password)
        self._id_token = self._cognito.id_token
        self._exchange_for_aws_creds()
        log.info("Pentair auth OK")

    def _exchange_for_aws_creds(self):
        client = boto3.client("cognito-identity", region_name=_AWS_REGION)
        logins = {f"{_COGNITO_ENDPOINT}/{_USER_POOL_ID}": self._id_token}
        identity = client.get_id(IdentityPoolId=_IDENTITY_POOL_ID, Logins=logins)
        creds = client.get_credentials_for_identity(
            IdentityId=identity["IdentityId"], Logins=logins
        )["Credentials"]
        self._access_key    = creds["AccessKeyId"]
        self._secret_key    = creds["SecretKey"]
        self._session_token = creds["SessionToken"]
        self._cred_expiry   = time.time() + _CRED_TTL_SECONDS

    def _refresh_if_needed(self):
        if time.time() >= self._cred_expiry:
            log.info("Refreshing Pentair credentials...")
            try:
                self._cognito.check_token()
                self._id_token = self._cognito.id_token
                self._exchange_for_aws_creds()
            except Exception:
                self._authenticate()

    def _aws_auth(self) -> AWS4Auth:
        return AWS4Auth(
            self._access_key, self._secret_key, _AWS_REGION, "execute-api",
            session_token=self._session_token,
        )

    def _headers(self) -> dict:
        return {
            "x-amz-id-token": self._id_token,
            "user-agent": "aws-amplify/4.3.10 react-native",
            "content-type": "application/json; charset=UTF-8",
        }

    # ------------------------------------------------------------------
    # Device discovery & status
    # ------------------------------------------------------------------

    def _discover_device(self):
        r = requests.get(
            _BASE_URL + _DEVICES_PATH,
            auth=self._aws_auth(),
            headers=self._headers(),
            timeout=15,
        )
        r.raise_for_status()
        for device in r.json().get("data", []):
            if device.get("deviceType") == "IF31" and device.get("status") == "ACTIVE":
                self._device_id = device["deviceId"]
                log.info("Found Pentair device: %s (%s)", self._device_id,
                         device.get("productInfo", {}).get("nickName", ""))
                return
        log.warning("No IF31 device found — check Pentair account")

    def _raw_status(self) -> Optional[dict]:
        payload = json.dumps({"deviceIds": [self._device_id]})
        r = requests.post(
            _BASE_URL + _DEVICE_STATUS_PATH,
            auth=self._aws_auth(),
            headers=self._headers(),
            data=payload,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        for device_data in data.get("response", {}).get("data", []):
            if device_data.get("deviceId") == self._device_id:
                return device_data
        return None

    def _fetch_status(self) -> Optional[PumpStatus]:
        raw = self._raw_status()
        if not raw:
            return None
        return _parse_status(raw)


# ------------------------------------------------------------------
# Field parsing (separated so MockPentairClient can reuse it)
# ------------------------------------------------------------------

def _parse_status(device_data: dict) -> PumpStatus:
    fields = device_data.get("fields", {})

    def fval(key, default=0):
        v = fields.get(key, {})
        val = v.get("value", default) if isinstance(v, dict) else default
        try:
            return float(val) if val != "" else float(default)
        except (TypeError, ValueError):
            return float(default)

    is_running  = int(fval("s3", 0)) == 1
    rpm         = int(fval("s17", 0))
    power_watts = fval("s18", 0.0)
    flow_gph    = fval("s26", 0.0) / 10.0 * 60.0  # s26: tenths GPM → GPH
    target_gph  = fval("s16", 0.0)     # program setpoint
    prog_idx    = int(fval("s14", 0))  # 0-based active program

    # Derive speed mode from active program name
    prog_key  = f"zp{prog_idx + 1}e2"
    prog_name = (fields.get(prog_key, {}).get("value", "") or "").lower()
    if "low" in prog_name:
        speed_mode = "low"
    elif "high" in prog_name:
        speed_mode = "high"
    else:
        speed_mode = "low" if rpm < 1500 else "high"

    return PumpStatus(
        rpm=rpm,
        power_watts=power_watts,
        flow_gph=flow_gph,
        is_running=is_running,
        speed_mode=speed_mode if is_running else "off",
        raw={
            "deviceId": device_data.get("deviceId"),
            "prog_idx": prog_idx,
            "prog_name": prog_name,
            "target_gph": target_gph,
            "fields_snapshot": {k: fields[k].get("value") if isinstance(fields[k], dict)
                                else fields[k] for k in ("s3","s14","s16","s17","s18","s19")
                                if k in fields},
        },
    )


# ------------------------------------------------------------------
# Mock client for tests
# ------------------------------------------------------------------

class MockPentairClient:
    """
    Test/development client that replays fixture files instead of hitting the cloud.
    Fixture files live in tests/fixtures/ as JSON matching the real API device_data format.
    """

    def __init__(self, fixture_path: Optional[Path] = None, sequence: Optional[list] = None):
        self._sequence = sequence or []
        self._index = 0
        if fixture_path:
            with open(fixture_path) as f:
                raw = json.load(f)
            self._sequence = [_fixture_to_status(raw)]

    def get_status(self) -> Optional[PumpStatus]:
        if not self._sequence:
            return None
        status = self._sequence[self._index % len(self._sequence)]
        self._index += 1
        return status

    def set_speed_program(self, program_index: int) -> bool:
        log.info("[MOCK] set_speed_program(%d)", program_index)
        return True

    def turn_off(self) -> bool:
        log.warning("[MOCK] turn_off()")
        return True

    def set_pump_enabled(self, enabled: bool) -> bool:
        log.warning("[MOCK] set_pump_enabled(%s)", enabled)
        return True


# ------------------------------------------------------------------
# Fixture helpers (tests use these directly)
# ------------------------------------------------------------------

def _fixture_to_status(raw: dict) -> PumpStatus:
    """Convert a fixture dict (synthetic or real API snapshot) to PumpStatus."""
    # Support both raw API format (has 'fields' key) and simplified fixture format
    if "fields" in raw:
        return _parse_status(raw)
    # Simplified fixture format used in tests
    rpm     = int(_extract(raw, ["rpm", "speed"], default=0))
    watts   = float(_extract(raw, ["watts", "power", "power_watts"], default=0.0))
    gph     = float(_extract(raw, ["gph", "flow", "flow_gph"], default=0.0))
    running = bool(_extract(raw, ["isRunning", "is_running", "running"], default=rpm > 0))
    return PumpStatus(rpm=rpm, power_watts=watts, flow_gph=gph, is_running=running, raw=raw)


def _extract(data: dict, keys: list, default=None):
    lowered = {k.lower(): v for k, v in data.items()}
    for key in keys:
        if key.lower() in lowered:
            return lowered[key.lower()]
    for v in data.values():
        if isinstance(v, dict):
            result = _extract(v, keys, default=None)
            if result is not None:
                return result
    return default

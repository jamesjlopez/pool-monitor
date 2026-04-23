#!/usr/bin/env python3
"""
Packet Parser
Extracts PSI/GPH/Power readings from intercepted pool controller API traffic.
Pair with sniffer_setup.sh (mitmproxy) to feed live packets here.
"""

import json
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class RawPacket:
    method: str
    url: str
    headers: dict = field(default_factory=dict)
    body: str = ""


@dataclass
class MetricPayload:
    psi: Optional[float] = None
    gph: Optional[float] = None
    power_watts: Optional[float] = None
    raw: dict = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return all(v is not None for v in [self.psi, self.gph, self.power_watts])


# ---------------------------------------------------------------------------
# Key mapping — update these once you've captured real traffic and know the
# actual field names your pool app uses.
# ---------------------------------------------------------------------------
_PSI_KEYS   = {"psi", "pressure", "filter_pressure", "filterpressure"}
_GPH_KEYS   = {"gph", "flow", "flowrate", "flow_rate", "gallons_per_hour"}
_POWER_KEYS = {"watts", "power", "power_w", "wattage", "current_power"}


def _fuzzy_find(data: dict, candidates: set) -> Optional[float]:
    for key, val in data.items():
        if key.lower().replace("-", "_") in candidates:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return None


def parse_json_body(body: str) -> Optional[MetricPayload]:
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None

    # Flatten one level of nesting (e.g. {"telemetry": {"psi": 12}})
    flat: dict = {}
    for k, v in data.items():
        if isinstance(v, dict):
            flat.update(v)
        else:
            flat[k] = v

    payload = MetricPayload(
        psi=_fuzzy_find(flat, _PSI_KEYS),
        gph=_fuzzy_find(flat, _GPH_KEYS),
        power_watts=_fuzzy_find(flat, _POWER_KEYS),
        raw=flat,
    )
    return payload if any(v is not None for v in [payload.psi, payload.gph, payload.power_watts]) else None


def parse_packet(packet: RawPacket) -> Optional[MetricPayload]:
    content_type = packet.headers.get("content-type", "")
    if "json" in content_type or packet.body.lstrip().startswith("{"):
        result = parse_json_body(packet.body)
        if result:
            log.debug("Parsed packet: PSI=%s GPH=%s W=%s", result.psi, result.gph, result.power_watts)
        return result
    return None


# ---------------------------------------------------------------------------
# mitmproxy addon — run with: mitmdump -s packet_parser.py --listen-port 8080
# ---------------------------------------------------------------------------
class PoolSniffer:
    def __init__(self):
        from monitor.engine import PoolMonitor, Reading
        self.monitor = PoolMonitor()

    def response(self, flow):
        from mitmproxy import http
        if not isinstance(flow, http.HTTPFlow):
            return
        pkt = RawPacket(
            method=flow.request.method,
            url=str(flow.request.url),
            headers=dict(flow.response.headers),
            body=flow.response.text or "",
        )
        result = parse_packet(pkt)
        if result and result.complete:
            from monitor.engine import Reading
            self.monitor.process(Reading(
                psi=result.psi,
                gph=result.gph,
                power_watts=result.power_watts,
            ))


addons = [PoolSniffer()]

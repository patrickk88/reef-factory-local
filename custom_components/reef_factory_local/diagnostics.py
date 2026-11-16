"""Diagnostics download for device entries and the cloud replacement entry. Secrets redacted."""
from __future__ import annotations

import time
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import ReefConfigEntry, is_cloud_entry

TO_REDACT = {"token", "key", "email", "password", "pass", "ssid", "psk", "upstream_ips"}


def _clean(obj: Any) -> Any:
    """Make decoded device data JSON friendly (bytes -> hex, tuples/sets -> lists)."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (bytes, bytearray)):
        return obj.hex()
    return obj


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ReefConfigEntry) -> dict[str, Any]:
    out: dict[str, Any] = {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        }
    }
    rt = entry.runtime_data
    if is_cloud_entry(entry):
        server = rt.server
        out["cloud_server"] = {
            "mode": server.mode,
            "app_passthrough": server.app_passthrough,
            "listen_errors": server.listen_errors,
        }
        out["devices"] = [
            {
                "serial": c.serial,
                "kind": c.device.kind,
                "connected": c.device.connected,
                "real_cloud_connected": c.device.cloud_connected,
                "silenced": c.device.silenced,
                "seconds_since_seen": round(time.monotonic() - c.device.last_seen, 1) if c.device.last_seen else None,
                "firmware": c.device.firmware,
                "data": async_redact_data(_clean(c.data or {}), TO_REDACT),
            }
            for c in rt.coordinators.values()
        ]
    else:
        client = rt.client
        out["device"] = {
            "serial": rt.serial,
            "kind": client.kind,
            "connected": client.connected,
            "busy": client.busy,
            "firmware": rt.firmware,
            "seconds_since_data": round(time.monotonic() - client.last_data, 1) if client.last_data else None,
            "last_error": client.last_error,
            "seconds_since_error": round(time.monotonic() - client.last_error_at, 1) if client.last_error_at else None,
            "data": async_redact_data(_clean(rt.data or {}), TO_REDACT),
        }
        if client.raw_frames:  # unknown device type: its messages as they came
            out["device"]["raw_frames"] = client.raw_frames
    return out

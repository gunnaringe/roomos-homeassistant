"""Diagnostics download with personal identifiers removed."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import RoomOSConfigEntry

TO_REDACT = {
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    "title",
    "unique_id",
    "serial_number",
    # Status tree
    "Address",
    "BroadcastName",
    "CustomStatus",
    "DeveloperId",
    "DeviceId",
    "DisplayName",
    "FQDN",
    "Fingerprint",
    "GuestToken",
    "ID",
    "LinkLocalAddress",
    "MacAddress",
    "Name",
    "Number",
    "PrimaryMgmtAddress",
    "RemoteNumber",
    "SerialNumber",
    "SessionId",
    "SipAddress",
    "SysName",
    "UDI",
    "URI",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: RoomOSConfigEntry
) -> dict[str, Any]:
    """Entry data and the current Status tree."""
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(
            {"title": entry.title, "unique_id": entry.unique_id, **entry.data},
            TO_REDACT,
        ),
        "connected": coordinator.client.connected,
        "status": async_redact_data(coordinator.data or {}, TO_REDACT),
    }

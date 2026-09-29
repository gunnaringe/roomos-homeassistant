"""Actions for anything the entities don't cover."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
import voluptuous as vol

from .api import RoomOSError
from .const import (
    ATTR_COMMAND,
    ATTR_NUMBER,
    ATTR_PARAMS,
    ATTR_PATH,
    ATTR_PROTOCOL,
    ATTR_VALUE,
    DOMAIN,
)
from .coordinator import RoomOSCoordinator

SERVICE_COMMAND = "command"
SERVICE_SET_CONFIGURATION = "set_configuration"
SERVICE_DIAL = "dial"

_DEVICE = {vol.Required(ATTR_DEVICE_ID): cv.string}

COMMAND_SCHEMA = vol.Schema(
    {
        **_DEVICE,
        vol.Required(ATTR_COMMAND): cv.string,
        vol.Optional(ATTR_PARAMS, default={}): dict,
    }
)
SET_CONFIGURATION_SCHEMA = vol.Schema(
    {
        **_DEVICE,
        vol.Required(ATTR_PATH): cv.string,
        vol.Required(ATTR_VALUE): vol.Any(str, int, float, bool),
    }
)
DIAL_SCHEMA = vol.Schema(
    {
        **_DEVICE,
        vol.Required(ATTR_NUMBER): cv.string,
        vol.Optional(ATTR_PROTOCOL): cv.string,
    }
)


def _coordinator(hass: HomeAssistant, device_id: str) -> RoomOSCoordinator:
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="unknown_device"
        )
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == DOMAIN:
            if entry.state is not ConfigEntryState.LOADED:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="not_loaded"
                )
            return entry.runtime_data
    raise ServiceValidationError(
        translation_domain=DOMAIN, translation_key="unknown_device"
    )


async def _run(coro: Any) -> Any:
    try:
        return await coro
    except RoomOSError as err:
        raise HomeAssistantError(str(err)) from err


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions once for all devices."""

    async def command(call: ServiceCall) -> ServiceResponse:
        client = _coordinator(hass, call.data[ATTR_DEVICE_ID]).client
        result = await _run(
            client.command(call.data[ATTR_COMMAND], call.data[ATTR_PARAMS])
        )
        return {"result": result}

    async def set_configuration(call: ServiceCall) -> None:
        client = _coordinator(hass, call.data[ATTR_DEVICE_ID]).client
        path = call.data[ATTR_PATH]
        if not path.replace("/", " ").split()[0].lower().startswith("configuration"):
            path = f"Configuration {path}"
        await _run(client.set(path, call.data[ATTR_VALUE]))

    async def dial(call: ServiceCall) -> None:
        client = _coordinator(hass, call.data[ATTR_DEVICE_ID]).client
        params = {"Number": call.data[ATTR_NUMBER]}
        if protocol := call.data.get(ATTR_PROTOCOL):
            params["Protocol"] = protocol
        await _run(client.command("Dial", params))

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMMAND,
        command,
        schema=COMMAND_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_CONFIGURATION,
        set_configuration,
        schema=SET_CONFIGURATION_SCHEMA,
    )
    hass.services.async_register(DOMAIN, SERVICE_DIAL, dial, schema=DIAL_SCHEMA)

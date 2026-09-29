"""Config flow: one entry per device, identified by its serial number."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .api import RoomOSAuthError, RoomOSClient, RoomOSError
from .const import DEFAULT_USERNAME, DOMAIN
from .entity import value_at

_LOGGER = logging.getLogger(__name__)


def _schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(
                CONF_USERNAME, default=defaults.get(CONF_USERNAME, DEFAULT_USERNAME)
            ): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(
                CONF_VERIFY_SSL, default=defaults.get(CONF_VERIFY_SSL, False)
            ): bool,
        }
    )


async def _probe(hass: HomeAssistant, data: Mapping[str, Any]) -> tuple[str, str]:
    """Connect once and return (serial number, suggested title)."""
    client = RoomOSClient(
        async_get_clientsession(hass, verify_ssl=data.get(CONF_VERIFY_SSL, False)),
        data[CONF_HOST],
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
    )
    try:
        status = await client.connect()
    finally:
        await client.close()
    serial = value_at(status, "SystemUnit.Hardware.Module.SerialNumber")
    if not serial:
        raise RoomOSError("Device did not report a serial number")
    title = (
        value_at(status, "SystemUnit.BroadcastName")
        or value_at(status, "UserInterface.ContactInfo.Name")
        or value_at(status, "SystemUnit.ProductId")
        or data[CONF_HOST]
    )
    return str(serial), str(title)


class RoomOSConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a RoomOS device."""

    VERSION = 1

    async def _try(
        self, data: Mapping[str, Any], errors: dict[str, str]
    ) -> tuple[str, str] | None:
        try:
            return await _probe(self.hass, data)
        except RoomOSAuthError:
            errors["base"] = "invalid_auth"
        except RoomOSError as err:
            _LOGGER.debug("Cannot connect to %s: %s", data[CONF_HOST], err)
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error probing %s", data[CONF_HOST])
            errors["base"] = "unknown"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for host and credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].strip()
            if found := await self._try(user_input, errors):
                serial, title = found
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: user_input[CONF_HOST]}
                )
                return self.async_create_entry(title=title, data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Credentials stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for new credentials."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input}
            if found := await self._try(data, errors):
                await self.async_set_unique_id(found[0])
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            description_placeholders={"name": entry.title},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change host, credentials or SSL verification."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].strip()
            if found := await self._try(user_input, errors):
                await self.async_set_unique_id(found[0])
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(entry, data=user_input)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or entry.data),
            errors=errors,
        )

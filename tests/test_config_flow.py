"""Config flow: add, duplicates, errors, reauth, reconfigure."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.cisco_roomos.const import DOMAIN

from .conftest import SERIAL, FakeRoomOS, entry_data, setup_device


async def _user_flow(hass: HomeAssistant, data: dict):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.flow.async_configure(result["flow_id"], data)


async def test_user_creates_entry(hass: HomeAssistant, device: FakeRoomOS) -> None:
    """Serial becomes the unique id, broadcast name the title."""
    result = await _user_flow(hass, entry_data(device.host))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Office Desk Mini"
    assert result["result"].unique_id == SERIAL
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(result["result"].entry_id)


async def test_user_invalid_auth(hass: HomeAssistant, device: FakeRoomOS) -> None:
    """Wrong password shows an error."""
    result = await _user_flow(hass, entry_data(device.host) | {CONF_PASSWORD: "no"})
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_cannot_connect(hass: HomeAssistant, socket_enabled) -> None:
    """Nothing listening shows an error."""
    result = await _user_flow(hass, entry_data("127.0.0.1:1"))
    assert result["errors"] == {"base": "cannot_connect"}


async def test_duplicate_updates_host(hass: HomeAssistant, device: FakeRoomOS) -> None:
    """Adding the same device again aborts and keeps the new host."""
    entry = await setup_device(hass, device)
    await hass.config_entries.async_unload(entry.entry_id)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_HOST: "192.0.2.99"}
    )
    result = await _user_flow(hass, entry_data(device.host))
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == device.host


async def test_reauth(hass: HomeAssistant, device: FakeRoomOS) -> None:
    """New password is stored and the entry reloads."""
    entry = await setup_device(hass, device)
    device.password = "rotated"
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "integrator", CONF_PASSWORD: "rotated"}
    )
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "rotated"
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reconfigure_wrong_device(
    hass: HomeAssistant, device: FakeRoomOS
) -> None:
    """Pointing an entry at another device's address is refused."""
    entry = await setup_device(hass, device, serial="OTHER")
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], entry_data(device.host)
    )
    assert result["reason"] == "wrong_device"
    await hass.config_entries.async_unload(entry.entry_id)

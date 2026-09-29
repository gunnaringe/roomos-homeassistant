"""Media player: power, volume, mute, call title."""

from __future__ import annotations

import asyncio

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant

from .conftest import FakeRoomOS, setup_device

ENTITY = "media_player.office"


async def test_media_player(hass: HomeAssistant, device: FakeRoomOS) -> None:
    """Standby maps to off, calls to playing; controls send xCommands."""
    entry = await setup_device(hass, device)
    state = hass.states.get(ENTITY)
    assert state.state == "off"

    await device.push(
        {
            "Standby": {"State": "Off"},
            "Call": [{"id": 1, "Status": "Connected", "DisplayName": "Ola"}],
        }
    )
    await asyncio.sleep(0.05)
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state.state == "playing"
    assert state.attributes["media_title"] == "Ola"
    assert state.attributes["volume_level"] == 0.3

    for service, data in (
        ("turn_off", {}),
        ("volume_set", {"volume_level": 0.55}),
        ("volume_mute", {"is_volume_muted": True}),
        ("volume_up", {}),
    ):
        await hass.services.async_call(
            "media_player", service, {ATTR_ENTITY_ID: ENTITY, **data}, blocking=True
        )
    assert device.commands()[-4:] == [
        ("xCommand/Standby/Activate", {}),
        ("xCommand/Audio/Volume/Set", {"Level": 55}),
        ("xCommand/Audio/Volume/Mute", {}),
        ("xCommand/Audio/Volume/Increase", {}),
    ]
    await hass.config_entries.async_unload(entry.entry_id)

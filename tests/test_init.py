"""Setup, entities, push updates, reconnects, services and diagnostics."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.cisco_roomos.const import DOMAIN, EVENT_ROOMOS
from custom_components.cisco_roomos.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import SERIAL, FakeRoomOS, setup_device


def _device(hass: HomeAssistant, entry) -> dr.DeviceEntry:
    (device,) = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    return device


async def _settle(hass: HomeAssistant) -> None:
    await asyncio.sleep(0.05)
    await hass.async_block_till_done()


@pytest.fixture
async def loaded(hass: HomeAssistant, device: FakeRoomOS):
    """One device set up; unloaded afterwards."""
    entry = await setup_device(hass, device)
    yield entry
    await hass.config_entries.async_unload(entry.entry_id)


async def test_entities(hass: HomeAssistant, device: FakeRoomOS, loaded) -> None:
    """States reflect the Desk Mini fixture; unsupported ones are skipped."""
    assert loaded.state is ConfigEntryState.LOADED
    expected = {
        "sensor.office_temperature": "23.1",
        "sensor.office_humidity": "50",
        "sensor.office_ambient_noise": "28",
        "sensor.office_people_count": "unknown",
        "sensor.office_standby_state": "standby",
        "sensor.office_call_status": "idle",
        "sensor.office_webex_presence": "Active",
        "sensor.office_booking_availability": "FreeUntil",
        "binary_sensor.office_in_call": "off",
        "binary_sensor.office_room_in_use": "off",
        "binary_sensor.office_camera_lid": "on",
        "binary_sensor.office_screen_on": "off",
        "switch.office_microphone_mute": "off",
        "switch.office_do_not_disturb": "off",
        "number.office_volume": "30",
    }
    for entity_id, state in expected.items():
        assert hass.states.get(entity_id).state == state, entity_id
    # The Desk Mini reports AirQualityIndex as "Unavailable".
    assert hass.states.get("sensor.office_air_quality_index") is None
    presence = hass.states.get("sensor.office_webex_presence")
    assert presence.attributes["custom_status"] == "Working from home"
    device_entry = _device(hass, loaded)
    assert device_entry.model == "Cisco Desk Mini"


async def test_push_updates(hass: HomeAssistant, device: FakeRoomOS, loaded) -> None:
    """Feedback moves states without polling."""
    await device.push(
        {
            "Audio": {"Volume": 45, "Microphones": {"Mute": "On"}},
            "RoomAnalytics": {"PeopleCount": {"Current": 1}, "RoomInUse": "True"},
            "SystemUnit": {"State": {"NumberOfActiveCalls": 1}},
            "Call": [{"id": 7, "Status": "Connected", "DisplayName": "Ola"}],
        }
    )
    await _settle(hass)
    assert hass.states.get("number.office_volume").state == "45"
    assert hass.states.get("switch.office_microphone_mute").state == "on"
    assert hass.states.get("sensor.office_people_count").state == "1"
    assert hass.states.get("binary_sensor.office_room_in_use").state == "on"
    assert hass.states.get("binary_sensor.office_in_call").state == "on"
    call = hass.states.get("sensor.office_call_status")
    assert call.state == "connected"
    assert call.attributes["display_name"] == "Ola"
    await device.push(
        {
            "Call": [{"id": 7, "ghost": "True"}],
            "SystemUnit": {"State": {"NumberOfActiveCalls": 0}},
        }
    )
    await _settle(hass)
    assert hass.states.get("sensor.office_call_status").state == "idle"


async def test_controls(hass: HomeAssistant, device: FakeRoomOS, loaded) -> None:
    """Switches, number and buttons send the right xCommands."""
    await hass.services.async_call(
        "switch",
        "turn_on",
        {ATTR_ENTITY_ID: "switch.office_microphone_mute"},
        blocking=True,
    )
    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: "number.office_volume", "value": 42},
        blocking=True,
    )
    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: "button.office_wake"}, blocking=True
    )
    assert device.commands()[-3:] == [
        ("xCommand/Audio/Microphones/Mute", {}),
        ("xCommand/Audio/Volume/Set", {"Level": 42}),
        ("xCommand/Standby/Deactivate", {}),
    ]


async def test_reconnect(hass: HomeAssistant, device: FakeRoomOS, loaded) -> None:
    """Entities go unavailable on disconnect and recover."""
    with patch("custom_components.cisco_roomos.coordinator.RECONNECT_MIN_DELAY", 0):
        await device.drop()
        await _settle(hass)
        assert hass.states.get("number.office_volume").state in (
            STATE_UNAVAILABLE,
            "30",
        )
        for _ in range(20):
            await _settle(hass)
            if hass.states.get("number.office_volume").state == "30":
                break
    assert hass.states.get("number.office_volume").state == "30"
    subscribes = [m for m, _ in device.requests if m == "xFeedback/Subscribe"]
    assert len(subscribes) == 4


async def test_events_fired(hass: HomeAssistant, device: FakeRoomOS, loaded) -> None:
    """xAPI events land on the HA bus with the device id."""
    events = async_capture_events(hass, EVENT_ROOMOS)
    await device.push_event(
        {"UserInterface": {"Extensions": {"Panel": {"Clicked": {"PanelId": "lights"}}}}}
    )
    await _settle(hass)
    device_entry = _device(hass, loaded)
    assert events[0].data["device_id"] == device_entry.id
    assert events[0].data["event"]["UserInterface"]["Extensions"]["Panel"]


async def test_services(hass: HomeAssistant, device: FakeRoomOS, loaded) -> None:
    """command returns the device result; dial and set_configuration send requests."""
    device_id = _device(hass, loaded).id
    device.results["xCommand/Bookings/List"] = {"ResultInfo": {"TotalRows": 0}}
    response = await hass.services.async_call(
        DOMAIN,
        "command",
        {"device_id": device_id, "command": "Bookings List", "params": {"Limit": 5}},
        blocking=True,
        return_response=True,
    )
    assert response == {"result": {"ResultInfo": {"TotalRows": 0}}}
    await hass.services.async_call(
        DOMAIN,
        "dial",
        {"device_id": device_id, "number": "a@b.c", "protocol": "Spark"},
        blocking=True,
    )
    assert device.requests[-1] == (
        "xCommand/Dial",
        {"Number": "a@b.c", "Protocol": "Spark"},
    )
    await hass.services.async_call(
        DOMAIN,
        "set_configuration",
        {"device_id": device_id, "path": "Audio DefaultVolume", "value": 40},
        blocking=True,
    )
    assert device.requests[-1] == (
        "xSet",
        {"Path": ["Configuration", "Audio", "DefaultVolume"], "Value": 40},
    )


async def test_two_devices(hass: HomeAssistant, device: FakeRoomOS, loaded) -> None:
    """A second device gets its own entry, device and entities."""
    second = await setup_device(
        hass, device, serial="FOC0000SECOND", title="Meeting room"
    )
    assert hass.states.get("sensor.meeting_room_temperature").state == "23.1"
    assert (
        len(dr.async_entries_for_config_entry(dr.async_get(hass), second.entry_id)) == 1
    )
    await hass.config_entries.async_unload(second.entry_id)


async def test_diagnostics_redacted(
    hass: HomeAssistant, device: FakeRoomOS, loaded
) -> None:
    """No password, serial or names in the download."""
    diag = await async_get_config_entry_diagnostics(hass, loaded)
    text = str(diag)
    for secret in ("secret", SERIAL, "Office Desk Mini", "00:11:22:33:44:55"):
        assert secret not in text


async def test_setup_retry_when_offline(
    hass: HomeAssistant, device: FakeRoomOS
) -> None:
    """Unreachable device → setup retry, not failure."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from .conftest import entry_data

    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=SERIAL, data=entry_data("127.0.0.1:1")
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_bad_credentials_start_reauth(
    hass: HomeAssistant, device: FakeRoomOS
) -> None:
    """401 at setup → reauth flow."""
    device.password = "changed"
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from .conftest import entry_data

    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=SERIAL, data=entry_data(device.host)
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(
        f["context"]["source"] == "reauth"
        for f in hass.config_entries.flow.async_progress()
    )

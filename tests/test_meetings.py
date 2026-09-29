"""Bookings: parsing, calendar, next meeting sensor and join button."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest

from custom_components.cisco_roomos.bookings import next_meeting, parse_bookings

from .conftest import FakeRoomOS, setup_device


def booking(
    booking_id: str, title: str, start_in: timedelta, minutes: int = 30, **extra
) -> dict:
    """A booking as Bookings List returns it."""
    start = dt_util.utcnow().replace(microsecond=0) + start_in
    return {
        "id": 1,
        "Id": booking_id,
        "Title": title,
        "Privacy": "Public",
        "Organizer": {"FirstName": "Kari", "LastName": "Nordmann"},
        "Time": {
            "StartTime": start.isoformat().replace("+00:00", "Z"),
            "EndTime": (start + timedelta(minutes=minutes))
            .isoformat()
            .replace("+00:00", "Z"),
        },
        "DialInfo": {
            "Calls": {
                "Call": [
                    {"id": 1, "Number": f"{booking_id}@webex.com", "Protocol": "Spark"}
                ]
            }
        },
    } | extra


def test_parse_skips_bad_and_sorts() -> None:
    """Missing times are dropped; result is sorted; private titles are masked."""
    meetings = parse_bookings(
        {
            "Booking": [
                booking("b2", "Later", timedelta(hours=2)),
                {"Id": "broken", "Time": {}},
                booking("b1", "", timedelta(hours=1), Privacy="Private"),
            ]
        }
    )
    assert [m.booking_id for m in meetings] == ["b1", "b2"]
    assert meetings[0].title == "Private meeting"
    assert meetings[0].organizer == "Kari Nordmann"
    assert meetings[0].joinable


def test_next_meeting_prefers_in_progress() -> None:
    """A running meeting beats the next one."""
    meetings = parse_bookings(
        {
            "Booking": [
                booking("done", "Done", -timedelta(hours=2)),
                booking("now", "Now", -timedelta(minutes=10)),
                booking("next", "Next", timedelta(hours=1)),
            ]
        }
    )
    assert next_meeting(meetings).booking_id == "now"
    assert parse_bookings({"ResultInfo": {"TotalRows": 0}}) == []


@pytest.fixture
async def with_meetings(hass: HomeAssistant, device: FakeRoomOS):
    """Device with two upcoming meetings."""
    device.results["xCommand/Bookings/List"] = {
        "Booking": [
            booking("b1", "Standup", timedelta(minutes=20)),
            booking("b2", "Planning", timedelta(hours=3), minutes=60),
        ]
    }
    entry = await setup_device(hass, device)
    yield entry
    await hass.config_entries.async_unload(entry.entry_id)


async def test_entities(hass: HomeAssistant, device: FakeRoomOS, with_meetings) -> None:
    """Calendar, sensor and join button reflect the next meeting."""
    sensor = hass.states.get("sensor.office_next_meeting")
    assert sensor.state == "Standup"
    assert sensor.attributes["organizer"] == "Kari Nordmann"
    assert len(sensor.attributes["meetings"]) == 2
    calendar = hass.states.get("calendar.office_meetings")
    assert calendar.attributes["message"] == "Standup"

    now = dt_util.utcnow()
    events = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            ATTR_ENTITY_ID: "calendar.office_meetings",
            "start_date_time": now,
            "end_date_time": now + timedelta(hours=2),
        },
        blocking=True,
        return_response=True,
    )
    assert [e["summary"] for e in events["calendar.office_meetings"]["events"]] == [
        "Standup"
    ]

    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: "button.office_join_meeting"}, blocking=True
    )
    assert device.requests[-1] == (
        "xCommand/Dial",
        {"Number": "b1@webex.com", "Protocol": "Spark", "BookingId": "b1"},
    )


async def test_bookings_event_refreshes(
    hass: HomeAssistant, device: FakeRoomOS, with_meetings
) -> None:
    """A Bookings event re-fetches the list."""
    device.results["xCommand/Bookings/List"] = {
        "Booking": [booking("b3", "Moved", timedelta(minutes=5))]
    }
    await device.push_event({"Bookings": {"Updated": {}}})
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.office_next_meeting").state == "Moved"


async def test_no_meetings(hass: HomeAssistant, device: FakeRoomOS) -> None:
    """Empty calendar: sensor unknown, join button unavailable."""
    entry = await setup_device(hass, device)
    assert hass.states.get("sensor.office_next_meeting").state == "unknown"
    assert hass.states.get("button.office_join_meeting").state == "unavailable"
    await hass.config_entries.async_unload(entry.entry_id)

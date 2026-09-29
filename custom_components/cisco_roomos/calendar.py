"""The device's bookings as a calendar."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .bookings import Meeting, next_meeting
from .coordinator import RoomOSConfigEntry
from .entity import RoomOSEntity

MEETINGS = EntityDescription(key="meetings", translation_key="meetings")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RoomOSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the calendar if the device keeps bookings."""
    coordinator = entry.runtime_data
    if coordinator.has_bookings:
        async_add_entities([RoomOSCalendar(coordinator, MEETINGS)])


def _event(meeting: Meeting) -> CalendarEvent:
    return CalendarEvent(
        start=meeting.start,
        end=meeting.end,
        summary=meeting.title,
        description=f"Organizer: {meeting.organizer}" if meeting.organizer else None,
        uid=meeting.booking_id or None,
    )


class RoomOSCalendar(RoomOSEntity, CalendarEntity):
    """Meetings booked on the device (typically today and tomorrow)."""

    # Plain EntityDescription has no initial_color (HA 2026.9+ reads it).
    _attr_initial_color = None

    @property
    def event(self) -> CalendarEvent | None:
        """Current or next meeting."""
        meeting = next_meeting(self.coordinator.meetings or [])
        return _event(meeting) if meeting else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Meetings overlapping the window."""
        start, end = dt_util.as_utc(start_date), dt_util.as_utc(end_date)
        return [
            _event(m)
            for m in self.coordinator.meetings or []
            if m.end > start and m.start < end
        ]

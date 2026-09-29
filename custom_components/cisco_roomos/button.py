"""Buttons: wake, standby, hang up, restart."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .bookings import next_meeting
from .coordinator import RoomOSConfigEntry
from .entity import RoomOSEntity, RoomOSEntityDescription


@dataclass(frozen=True, kw_only=True)
class RoomOSButtonDescription(RoomOSEntityDescription, ButtonEntityDescription):
    """xCommand a button sends."""

    command: str
    params: dict[str, Any] | None = None


BUTTONS: tuple[RoomOSButtonDescription, ...] = (
    RoomOSButtonDescription(
        key="wake",
        translation_key="wake",
        command="Standby Deactivate",
    ),
    RoomOSButtonDescription(
        key="standby",
        translation_key="standby",
        command="Standby Activate",
    ),
    RoomOSButtonDescription(
        key="halfwake",
        translation_key="halfwake",
        entity_registry_enabled_default=False,
        command="Standby Halfwake",
    ),
    RoomOSButtonDescription(
        key="hang_up",
        translation_key="hang_up",
        command="Call Disconnect",
    ),
    RoomOSButtonDescription(
        key="restart",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        command="SystemUnit Boot",
        params={"Action": "Restart"},
    ),
)


JOIN_MEETING = ButtonEntityDescription(
    key="join_meeting", translation_key="join_meeting"
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RoomOSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the buttons."""
    coordinator = entry.runtime_data
    entities: list[ButtonEntity] = [RoomOSButton(coordinator, d) for d in BUTTONS]
    if coordinator.has_bookings:
        entities.append(RoomOSJoinMeetingButton(coordinator, JOIN_MEETING))
    async_add_entities(entities)


class RoomOSButton(RoomOSEntity, ButtonEntity):
    """Run one xCommand."""

    entity_description: RoomOSButtonDescription

    async def async_press(self) -> None:
        """Send the command."""
        await self._command(
            self.entity_description.command, self.entity_description.params
        )


class RoomOSJoinMeetingButton(RoomOSEntity, ButtonEntity):
    """Dial into the meeting in progress or up next."""

    @property
    def available(self) -> bool:
        """Only when there is a meeting with dial info."""
        meeting = next_meeting(self.coordinator.meetings or [])
        return super().available and meeting is not None and meeting.joinable

    async def async_press(self) -> None:
        """Dial the meeting's number."""
        meeting = next_meeting(self.coordinator.meetings or [])
        if meeting is None or not meeting.joinable:
            raise HomeAssistantError("No joinable meeting")
        params: dict[str, Any] = {"Number": meeting.number}
        if meeting.protocol:
            params["Protocol"] = meeting.protocol
        if meeting.booking_id:
            params["BookingId"] = meeting.booking_id
        await self._command("Dial", params)

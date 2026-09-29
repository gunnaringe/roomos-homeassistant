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
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RoomOSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the buttons."""
    coordinator = entry.runtime_data
    async_add_entities(RoomOSButton(coordinator, d) for d in BUTTONS)


class RoomOSButton(RoomOSEntity, ButtonEntity):
    """Run one xCommand."""

    entity_description: RoomOSButtonDescription

    async def async_press(self) -> None:
        """Send the command."""
        await self._command(
            self.entity_description.command, self.entity_description.params
        )

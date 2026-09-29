"""Switches: microphone mute, speaker mute, do not disturb, selfview."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import RoomOSConfigEntry
from .entity import RoomOSEntity, RoomOSEntityDescription, Status, is_value, value_at


@dataclass(frozen=True, kw_only=True)
class RoomOSSwitchDescription(RoomOSEntityDescription, SwitchEntityDescription):
    """Status path to read and xCommands to flip it."""

    is_on_fn: Callable[[Status], bool | None]
    on_command: tuple[str, dict[str, Any] | None]
    off_command: tuple[str, dict[str, Any] | None]


SWITCHES: tuple[RoomOSSwitchDescription, ...] = (
    RoomOSSwitchDescription(
        key="microphone_mute",
        translation_key="microphone_mute",
        exists_path="Audio.Microphones.Mute",
        is_on_fn=lambda s: is_value(value_at(s, "Audio.Microphones.Mute"), "on"),
        on_command=("Audio Microphones Mute", None),
        off_command=("Audio Microphones Unmute", None),
    ),
    RoomOSSwitchDescription(
        key="speaker_mute",
        translation_key="speaker_mute",
        exists_path="Audio.VolumeMute",
        is_on_fn=lambda s: is_value(value_at(s, "Audio.VolumeMute"), "on"),
        on_command=("Audio Volume Mute", None),
        off_command=("Audio Volume Unmute", None),
    ),
    RoomOSSwitchDescription(
        key="do_not_disturb",
        translation_key="do_not_disturb",
        exists_path="Conference.DoNotDisturb",
        is_on_fn=lambda s: is_value(value_at(s, "Conference.DoNotDisturb"), "active"),
        on_command=("Conference DoNotDisturb Activate", None),
        off_command=("Conference DoNotDisturb Deactivate", None),
    ),
    RoomOSSwitchDescription(
        key="selfview",
        translation_key="selfview",
        entity_registry_enabled_default=False,
        exists_path="Video.Selfview.Mode",
        is_on_fn=lambda s: is_value(value_at(s, "Video.Selfview.Mode"), "on"),
        on_command=("Video Selfview Set", {"Mode": "On"}),
        off_command=("Video Selfview Set", {"Mode": "Off"}),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RoomOSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the switches this device supports."""
    coordinator = entry.runtime_data
    async_add_entities(
        RoomOSSwitch(coordinator, description)
        for description in SWITCHES
        if description.supported(coordinator.data or {})
    )


class RoomOSSwitch(RoomOSEntity, SwitchEntity):
    """Flip a device setting; state comes back through feedback."""

    entity_description: RoomOSSwitchDescription

    @property
    def is_on(self) -> bool | None:
        """Current state."""
        return self.entity_description.is_on_fn(self.status)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Send the 'on' command."""
        await self._command(*self.entity_description.on_command)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Send the 'off' command."""
        await self._command(*self.entity_description.off_command)

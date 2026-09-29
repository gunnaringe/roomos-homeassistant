"""The device as a media player: power (standby), volume and mute."""

from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .binary_sensor import ACTIVE_CALL_STATES
from .coordinator import RoomOSConfigEntry
from .entity import RoomOSEntity, as_number, calls, has_path, is_value, value_at

DEVICE = EntityDescription(key="media_player", name=None)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RoomOSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the media player."""
    coordinator = entry.runtime_data
    if has_path(coordinator.data or {}, "Audio.Volume"):
        async_add_entities([RoomOSMediaPlayer(coordinator, DEVICE)])


class RoomOSMediaPlayer(RoomOSEntity, MediaPlayerEntity):
    """Off in standby, playing while in a call, on otherwise."""

    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
    )

    @property
    def state(self) -> MediaPlayerState | None:
        """Standby → off; active call → playing; else on."""
        standby = value_at(self.status, "Standby.State")
        if is_value(standby, "standby", "enteringstandby"):
            return MediaPlayerState.OFF
        if any(
            is_value(c.get("Status"), *ACTIVE_CALL_STATES) for c in calls(self.status)
        ):
            return MediaPlayerState.PLAYING
        return MediaPlayerState.ON

    @property
    def volume_level(self) -> float | None:
        """Volume 0..1."""
        volume = as_number(value_at(self.status, "Audio.Volume"))
        return None if volume is None else volume / 100

    @property
    def is_volume_muted(self) -> bool | None:
        """Speaker mute."""
        return is_value(value_at(self.status, "Audio.VolumeMute"), "on")

    @property
    def media_title(self) -> str | None:
        """Who you're talking to."""
        active = calls(self.status)
        if not active:
            return None
        return active[0].get("DisplayName") or active[0].get("RemoteNumber")

    async def async_turn_on(self) -> None:
        """Wake from standby."""
        await self._command("Standby Deactivate")

    async def async_turn_off(self) -> None:
        """Go to standby."""
        await self._command("Standby Activate")

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume."""
        await self._command("Audio Volume Set", {"Level": round(volume * 100)})

    async def async_volume_up(self) -> None:
        """Step up."""
        await self._command("Audio Volume Increase")

    async def async_volume_down(self) -> None:
        """Step down."""
        await self._command("Audio Volume Decrease")

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute the speaker."""
        await self._command("Audio Volume Mute" if mute else "Audio Volume Unmute")

"""Volume as a number entity."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import RoomOSConfigEntry
from .entity import RoomOSEntity, as_number, has_path, value_at

VOLUME = NumberEntityDescription(
    key="volume_level",
    translation_key="volume_level",
    native_min_value=0,
    native_max_value=100,
    native_step=1,
    native_unit_of_measurement=PERCENTAGE,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RoomOSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the volume control."""
    coordinator = entry.runtime_data
    if has_path(coordinator.data or {}, "Audio.Volume"):
        async_add_entities([RoomOSVolume(coordinator, VOLUME)])


class RoomOSVolume(RoomOSEntity, NumberEntity):
    """Speaker volume, 0-100."""

    @property
    def native_value(self) -> float | None:
        """Current volume."""
        return as_number(value_at(self.status, "Audio.Volume"))

    async def async_set_native_value(self, value: float) -> None:
        """Set the volume."""
        await self._command("Audio Volume Set", {"Level": int(value)})

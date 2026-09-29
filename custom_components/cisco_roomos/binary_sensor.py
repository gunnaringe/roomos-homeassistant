"""Binary sensors: calls, occupancy and device state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import RoomOSConfigEntry
from .entity import (
    RoomOSEntity,
    RoomOSEntityDescription,
    Status,
    as_number,
    calls,
    is_value,
    value_at,
)

ACTIVE_CALL_STATES = {"connected", "connecting", "onhold", "earlymedia"}


@dataclass(frozen=True, kw_only=True)
class RoomOSBinarySensorDescription(
    RoomOSEntityDescription, BinarySensorEntityDescription
):
    """How to read one on/off value from the Status tree."""

    is_on_fn: Callable[[Status], bool | None]


def _in_call(status: Status) -> bool:
    if (
        n := as_number(value_at(status, "SystemUnit.State.NumberOfActiveCalls"))
    ) is not None:
        return n > 0
    return any(is_value(c.get("Status"), *ACTIVE_CALL_STATES) for c in calls(status))


def _flag(path: str, *truthy: str) -> Callable[[Status], bool | None]:
    def read(status: Status) -> bool | None:
        value = value_at(status, path)
        return None if value is None else is_value(value, *truthy)

    return read


BINARY_SENSORS: tuple[RoomOSBinarySensorDescription, ...] = (
    RoomOSBinarySensorDescription(
        key="in_call",
        translation_key="in_call",
        device_class=BinarySensorDeviceClass.RUNNING,
        is_on_fn=_in_call,
    ),
    RoomOSBinarySensorDescription(
        key="room_in_use",
        translation_key="room_in_use",
        device_class=BinarySensorDeviceClass.OCCUPANCY,
        exists_path="RoomAnalytics.RoomInUse",
        is_on_fn=_flag("RoomAnalytics.RoomInUse", "true"),
    ),
    RoomOSBinarySensorDescription(
        key="people_presence",
        translation_key="people_presence",
        device_class=BinarySensorDeviceClass.OCCUPANCY,
        exists_path="RoomAnalytics.PeoplePresence",
        is_on_fn=_flag("RoomAnalytics.PeoplePresence", "yes"),
    ),
    RoomOSBinarySensorDescription(
        key="close_proximity",
        translation_key="close_proximity",
        device_class=BinarySensorDeviceClass.OCCUPANCY,
        exists_path="RoomAnalytics.Engagement.CloseProximity",
        is_on_fn=_flag("RoomAnalytics.Engagement.CloseProximity", "true"),
    ),
    RoomOSBinarySensorDescription(
        key="presenting",
        translation_key="presenting",
        exists_path="Conference.Presentation.Mode",
        is_on_fn=lambda s: (
            not is_value(value_at(s, "Conference.Presentation.Mode"), "off")
            or bool(value_at(s, "Conference.Presentation.LocalInstance"))
        ),
    ),
    RoomOSBinarySensorDescription(
        key="screen_on",
        translation_key="screen_on",
        exists_path="Standby.State",
        is_on_fn=_flag("Standby.State", "off", "halfwake"),
    ),
    RoomOSBinarySensorDescription(
        key="camera_lid",
        translation_key="camera_lid",
        device_class=BinarySensorDeviceClass.OPENING,
        exists_path="SystemUnit.State.CameraLid",
        is_on_fn=_flag("SystemUnit.State.CameraLid", "open"),
    ),
    RoomOSBinarySensorDescription(
        key="smoke_alarm",
        translation_key="smoke_alarm",
        device_class=BinarySensorDeviceClass.SMOKE,
        exists_path="RoomAnalytics.T3Alarm.Detected",
        is_on_fn=_flag("RoomAnalytics.T3Alarm.Detected", "true"),
    ),
    RoomOSBinarySensorDescription(
        key="webex_registered",
        translation_key="webex_registered",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_path="Webex.Status",
        is_on_fn=_flag("Webex.Status", "registered"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RoomOSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the binary sensors this device supports."""
    coordinator = entry.runtime_data
    async_add_entities(
        RoomOSBinarySensor(coordinator, description)
        for description in BINARY_SENSORS
        if description.supported(coordinator.data or {})
    )


class RoomOSBinarySensor(RoomOSEntity, BinarySensorEntity):
    """An on/off value read from the Status tree."""

    entity_description: RoomOSBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Current state."""
        return self.entity_description.is_on_fn(self.status)

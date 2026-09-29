"""Sensors: room analytics, device state and diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfSoundPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import RoomOSConfigEntry
from .entity import (
    RoomOSEntity,
    RoomOSEntityDescription,
    Status,
    as_number,
    calls,
    value_at,
)

STANDBY_STATES = ["off", "halfwake", "enteringstandby", "standby"]
CALL_STATES = [
    "idle",
    "dialling",
    "ringing",
    "connecting",
    "connected",
    "disconnecting",
    "onhold",
    "earlymedia",
    "preserved",
    "remotepreserved",
]


@dataclass(frozen=True, kw_only=True)
class RoomOSSensorDescription(RoomOSEntityDescription, SensorEntityDescription):
    """How to read one sensor from the Status tree."""

    value_fn: Callable[[Status], Any]
    attrs_fn: Callable[[Status], dict[str, Any]] | None = None


def _first(status: Status, *paths: str, negative_is_none: bool = False) -> Any:
    """First numeric reading among alternative paths (models differ)."""
    for path in paths:
        if (
            v := as_number(value_at(status, path), negative_is_none=negative_is_none)
        ) is not None:
            return v
    return None


def _lower(value: Any) -> str | None:
    return str(value).lower() if value not in (None, "") else None


def _last_boot(status: Status) -> datetime | None:
    uptime = as_number(value_at(status, "SystemUnit.Uptime"))
    if uptime is None:
        return None
    now = (
        dt_util.parse_datetime(str(value_at(status, "Time.SystemTime") or ""))
        or dt_util.utcnow()
    )
    return (now - timedelta(seconds=uptime)).replace(microsecond=0)


def _call_state(status: Status) -> str:
    active = calls(status)
    return _lower(active[0].get("Status")) or "idle" if active else "idle"


def _call_attrs(status: Status) -> dict[str, Any]:
    active = calls(status)
    if not active:
        return {}
    call = active[0]
    return {
        "remote_number": call.get("RemoteNumber"),
        "display_name": call.get("DisplayName"),
        "direction": call.get("Direction"),
        "call_type": call.get("CallType"),
        "protocol": call.get("Protocol"),
    }


SENSORS: tuple[RoomOSSensorDescription, ...] = (
    RoomOSSensorDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        exists_fn=lambda s: (
            _first(
                s,
                "RoomAnalytics.AmbientTemperature",
                "RoomAnalytics.InsideRoom.AmbientTemperature",
            )
            is not None
        ),
        value_fn=lambda s: _first(
            s,
            "RoomAnalytics.AmbientTemperature",
            "RoomAnalytics.InsideRoom.AmbientTemperature",
        ),
    ),
    RoomOSSensorDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        exists_fn=lambda s: (
            _first(
                s,
                "RoomAnalytics.RelativeHumidity",
                "RoomAnalytics.InsideRoom.RelativeHumidity",
                negative_is_none=True,
            )
            is not None
        ),
        value_fn=lambda s: _first(
            s,
            "RoomAnalytics.RelativeHumidity",
            "RoomAnalytics.InsideRoom.RelativeHumidity",
            negative_is_none=True,
        ),
    ),
    RoomOSSensorDescription(
        key="air_quality_index",
        translation_key="air_quality_index",
        state_class=SensorStateClass.MEASUREMENT,
        exists_fn=lambda s: (
            _first(
                s,
                "RoomAnalytics.AirQuality.Index",
                "RoomAnalytics.InsideRoom.AirQualityIndex",
            )
            is not None
        ),
        value_fn=lambda s: _first(
            s,
            "RoomAnalytics.AirQuality.Index",
            "RoomAnalytics.InsideRoom.AirQualityIndex",
        ),
    ),
    RoomOSSensorDescription(
        key="ambient_noise",
        translation_key="ambient_noise",
        device_class=SensorDeviceClass.SOUND_PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSoundPressure.WEIGHTED_DECIBEL_A,
        exists_path="RoomAnalytics.AmbientNoise.Level.A",
        value_fn=lambda s: as_number(value_at(s, "RoomAnalytics.AmbientNoise.Level.A")),
    ),
    RoomOSSensorDescription(
        key="sound_level",
        translation_key="sound_level",
        device_class=SensorDeviceClass.SOUND_PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSoundPressure.WEIGHTED_DECIBEL_A,
        exists_path="RoomAnalytics.Sound.Level.A",
        value_fn=lambda s: as_number(value_at(s, "RoomAnalytics.Sound.Level.A")),
    ),
    RoomOSSensorDescription(
        key="people_count",
        translation_key="people_count",
        state_class=SensorStateClass.MEASUREMENT,
        exists_path="RoomAnalytics.PeopleCount.Current",
        # -1 while counting is inactive (device asleep / feature off).
        value_fn=lambda s: as_number(
            value_at(s, "RoomAnalytics.PeopleCount.Current"), negative_is_none=True
        ),
    ),
    RoomOSSensorDescription(
        key="standby_state",
        translation_key="standby_state",
        device_class=SensorDeviceClass.ENUM,
        options=STANDBY_STATES,
        exists_path="Standby.State",
        value_fn=lambda s: (
            v if (v := _lower(value_at(s, "Standby.State"))) in STANDBY_STATES else None
        ),
    ),
    RoomOSSensorDescription(
        key="call_status",
        translation_key="call_status",
        device_class=SensorDeviceClass.ENUM,
        options=CALL_STATES,
        value_fn=lambda s: v if (v := _call_state(s)) in CALL_STATES else None,
        attrs_fn=_call_attrs,
    ),
    RoomOSSensorDescription(
        key="webex_presence",
        translation_key="webex_presence",
        exists_path="Webex.Services.UserPresence.Status",
        value_fn=lambda s: value_at(s, "Webex.Services.UserPresence.Status"),
        attrs_fn=lambda s: {
            "custom_status": value_at(s, "Webex.Services.UserPresence.CustomStatus")
            or None
        },
    ),
    RoomOSSensorDescription(
        key="booking_availability",
        translation_key="booking_availability",
        exists_path="Bookings.Availability.Status",
        value_fn=lambda s: value_at(s, "Bookings.Availability.Status"),
        attrs_fn=lambda s: {
            "until": dt_util.parse_datetime(
                str(value_at(s, "Bookings.Availability.TimeStamp") or "")
            )
        },
    ),
    RoomOSSensorDescription(
        key="last_boot",
        translation_key="last_boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_path="SystemUnit.Uptime",
        value_fn=_last_boot,
    ),
    RoomOSSensorDescription(
        key="software_version",
        translation_key="software_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_path="SystemUnit.Software.DisplayName",
        value_fn=lambda s: value_at(s, "SystemUnit.Software.DisplayName"),
    ),
    RoomOSSensorDescription(
        key="ip_address",
        translation_key="ip_address",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        exists_path="Network.IPv4.Address",
        value_fn=lambda s: value_at(s, "Network.IPv4.Address"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RoomOSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors this device supports."""
    coordinator = entry.runtime_data
    async_add_entities(
        RoomOSSensor(coordinator, description)
        for description in SENSORS
        if description.supported(coordinator.data or {})
    )


class RoomOSSensor(RoomOSEntity, SensorEntity):
    """A value read from the Status tree."""

    entity_description: RoomOSSensorDescription

    @property
    def native_value(self) -> Any:
        """Current reading."""
        return self.entity_description.value_fn(self.status)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Extra details, if the description has any."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.status)

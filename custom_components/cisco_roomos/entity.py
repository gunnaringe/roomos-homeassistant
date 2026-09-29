"""Shared entity base and Status-tree helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import RoomOSError
from .const import DOMAIN
from .coordinator import RoomOSCoordinator

# Values RoomOS uses for "no reading" on analytics nodes.
NO_VALUE = {"", "unavailable", "unknown", "n/a"}

type Status = dict[str, Any]


def value_at(status: Status, path: str) -> Any:
    """Walk ``A.B.C``; multi-instance lists resolve to their first instance."""
    node: Any = status
    for key in path.split("."):
        if isinstance(node, list):
            node = node[0] if node else None
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def has_path(status: Status, path: str) -> bool:
    """Whether the device reports this node at all."""
    return value_at(status, path) is not None


def as_number(value: Any, *, negative_is_none: bool = False) -> float | int | None:
    """Parse a numeric reading; ``Unavailable``/``-1`` style values become None."""
    if value is None or (isinstance(value, str) and value.strip().lower() in NO_VALUE):
        return None
    try:
        number = float(value)
    except TypeError, ValueError:
        return None
    if negative_is_none and number < 0:
        return None
    return int(number) if number.is_integer() else number


def is_value(value: Any, *truthy: str) -> bool:
    """Case-insensitive compare of a status value against accepted strings."""
    return value is not None and str(value).lower() in {t.lower() for t in truthy}


def calls(status: Status) -> list[dict[str, Any]]:
    """Active call instances (``Status.Call`` is absent when idle)."""
    call = status.get("Call")
    if isinstance(call, dict):
        return [call]
    return [c for c in call or [] if isinstance(c, dict)]


@dataclass(frozen=True, kw_only=True)
class RoomOSEntityDescription(EntityDescription):
    """Common fields: which node the entity needs to exist."""

    # Entity is only created if the device reports this path at setup.
    exists_path: str | None = None
    exists_fn: Callable[[Status], bool] | None = None

    def supported(self, status: Status) -> bool:
        """Whether this device has what the entity needs."""
        if self.exists_fn is not None:
            return self.exists_fn(status)
        return self.exists_path is None or has_path(status, self.exists_path)


class RoomOSEntity(CoordinatorEntity[RoomOSCoordinator]):
    """Base: one device per config entry, keyed on the serial number."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: RoomOSCoordinator, description: EntityDescription
    ) -> None:
        """Attach to the device described by the coordinator's entry."""
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        status = coordinator.data or {}
        mac = value_at(status, "Network.Ethernet.MacAddress")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            connections={(CONNECTION_NETWORK_MAC, mac.lower())} if mac else set(),
            manufacturer="Cisco",
            model=value_at(status, "SystemUnit.ProductId"),
            model_id=value_at(status, "SystemUnit.ProductPlatform"),
            name=entry.title,
            serial_number=entry.unique_id,
            sw_version=value_at(status, "SystemUnit.Software.DisplayName"),
            configuration_url=f"https://{entry.data['host']}",
        )

    @property
    def status(self) -> Status:
        """Current Status tree."""
        return self.coordinator.data or {}

    async def _command(self, path: str, params: dict[str, Any] | None = None) -> None:
        try:
            await self.coordinator.client.command(path, params)
        except RoomOSError as err:
            raise HomeAssistantError(str(err)) from err

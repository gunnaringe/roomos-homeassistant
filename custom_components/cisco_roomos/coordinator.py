"""Push coordinator: owns the WebSocket and reconnects when it drops."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RoomOSAuthError, RoomOSClient, RoomOSConnectionError, RoomOSError
from .const import DOMAIN, EVENT_ROOMOS, RECONNECT_MAX_DELAY, RECONNECT_MIN_DELAY

_LOGGER = logging.getLogger(__name__)

type RoomOSConfigEntry = ConfigEntry[RoomOSCoordinator]


class RoomOSCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Holds the device's Status tree; updated by xFeedback, not polling."""

    config_entry: RoomOSConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: RoomOSConfigEntry, client: RoomOSClient
    ) -> None:
        """Wire the client callbacks to the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=None,
            always_update=True,
        )
        self.client = client
        self._reconnect_task: asyncio.Task[None] | None = None
        self._closing = False
        client.on_status = self._on_status
        client.on_event = self._on_event
        client.on_disconnect = self._on_disconnect

    async def _async_update_data(self) -> dict[str, Any]:
        """Connect (first refresh) or hand back the cached tree."""
        if self.client.connected:
            return self.client.status
        try:
            return await self.client.connect()
        except RoomOSAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except RoomOSError as err:
            raise UpdateFailed(str(err)) from err

    async def async_shutdown(self) -> None:
        """Stop reconnecting and close the socket."""
        self._closing = True
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
        await self.client.close()
        await super().async_shutdown()

    @callback
    def _on_status(self, status: dict[str, Any]) -> None:
        self.async_set_updated_data(status)

    @callback
    def _on_event(self, event: dict[str, Any]) -> None:
        devices = dr.async_entries_for_config_entry(
            dr.async_get(self.hass), self.config_entry.entry_id
        )
        self.hass.bus.async_fire(
            EVENT_ROOMOS,
            {"device_id": devices[0].id if devices else None, "event": event},
        )

    @callback
    def _on_disconnect(self, error: Exception | None) -> None:
        if self._closing:
            return
        _LOGGER.warning(
            "Lost connection to %s (%s); reconnecting", self.config_entry.title, error
        )
        self.async_set_update_error(RoomOSConnectionError("Connection lost"))
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = self.config_entry.async_create_background_task(
                self.hass, self._reconnect(), f"{DOMAIN} reconnect"
            )

    async def _reconnect(self) -> None:
        delay = RECONNECT_MIN_DELAY
        while not self._closing:
            await asyncio.sleep(delay)
            try:
                status = await self.client.connect()
            except RoomOSAuthError:
                _LOGGER.error("%s rejected the credentials", self.config_entry.title)
                self.config_entry.async_start_reauth(self.hass)
                return
            except RoomOSError as err:
                _LOGGER.debug(
                    "Reconnect to %s failed: %s", self.config_entry.title, err
                )
                delay = min(delay * 2, RECONNECT_MAX_DELAY)
                continue
            _LOGGER.info("Reconnected to %s", self.config_entry.title)
            self.async_set_updated_data(status)
            return

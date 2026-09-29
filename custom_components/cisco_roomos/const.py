"""Constants for the Cisco RoomOS integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "cisco_roomos"

DEFAULT_USERNAME: Final = "admin"

# Reconnect backoff when the WebSocket drops.
RECONNECT_MIN_DELAY: Final = 2
RECONNECT_MAX_DELAY: Final = 60

# Fired on the HA bus for every xAPI event (UI extension clicks, etc.).
EVENT_ROOMOS: Final = f"{DOMAIN}_event"

ATTR_COMMAND: Final = "command"
ATTR_PARAMS: Final = "params"
ATTR_PATH: Final = "path"
ATTR_VALUE: Final = "value"
ATTR_NUMBER: Final = "number"
ATTR_PROTOCOL: Final = "protocol"

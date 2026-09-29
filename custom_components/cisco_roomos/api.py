"""Client for the Cisco RoomOS xAPI over WebSocket (JSON-RPC 2.0).

The device exposes ``wss://<host>/ws``. Once connected we:

1. ``xGet`` the whole ``Status`` tree,
2. ``xFeedback/Subscribe`` to ``Status`` and ``Event``,
3. merge every ``xFeedback/Event`` notification into the cached tree.

Multi-instance nodes (``Call``, ``Network``, ...) arrive as lists of objects
carrying an ``id``. A removed instance is announced as ``{"id": n, "ghost":
"True"}`` and dropped from the cache.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
import contextlib
import copy
import itertools
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
HEARTBEAT = 30

type StatusCallback = Callable[[dict[str, Any]], None]
type EventCallback = Callable[[dict[str, Any]], None]
type DisconnectCallback = Callable[[Exception | None], None]


class RoomOSError(Exception):
    """Base error for the RoomOS client."""


class RoomOSConnectionError(RoomOSError):
    """The device could not be reached or the socket dropped."""


class RoomOSAuthError(RoomOSError):
    """The device rejected the credentials."""


class RoomOSCommandError(RoomOSError):
    """The device returned a JSON-RPC error for a request."""

    def __init__(self, method: str, error: dict[str, Any]) -> None:
        """Keep the device's error payload around."""
        self.method = method
        self.code = error.get("code")
        self.data = error.get("data")
        message = error.get("message", "unknown error")
        if isinstance(self.data, dict) and self.data.get("Reason"):
            message = f"{message}: {self.data['Reason']}"
        super().__init__(f"{method} failed: {message}")


def merge_status(target: dict[str, Any], update: dict[str, Any]) -> bool:
    """Merge a feedback fragment into the cached tree; True if anything changed.

    The device sends a steady stream of empty fragments (``{"Diagnostics":
    {}}``, Spark keep-alives, ...); those are no-ops.
    """
    changed = False
    for key, value in update.items():
        if isinstance(value, list):
            current = target.get(key)
            if not isinstance(current, list):
                current = [] if current is None else [current]
            before = copy.deepcopy(current)
            merged = _merge_instances(current, value)
            if merged != before:
                target[key] = merged
                changed = True
        elif isinstance(value, dict):
            if not value:
                continue
            if isinstance(target.get(key), dict):
                changed |= merge_status(target[key], value)
            else:
                node: dict[str, Any] = {}
                if merge_status(node, value):
                    target[key] = node
                    changed = True
        elif target.get(key) != value:
            target[key] = value
            changed = True
    return changed


def _merge_instances(current: list[Any], update: list[Any]) -> list[Any]:
    by_id = {item.get("id"): item for item in current if isinstance(item, dict)}
    order = [item.get("id") for item in current if isinstance(item, dict)]
    for item in update:
        if not isinstance(item, dict) or "id" not in item:
            # Plain value list: nothing to merge against, take it as-is.
            return copy.deepcopy(update)
        item_id = item["id"]
        if str(item.get("ghost", "")).lower() == "true":
            by_id.pop(item_id, None)
            continue
        if item_id in by_id:
            merge_status(by_id[item_id], item)
        else:
            by_id[item_id] = copy.deepcopy(item)
            order.append(item_id)
    return [by_id[i] for i in order if i in by_id]


class RoomOSClient:
    """A single WebSocket session to one RoomOS device."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
    ) -> None:
        """Store connection details; nothing happens until connect()."""
        self._session = session
        self._host = host
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self._headers = {"Authorization": f"Basic {token}"}
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._reader: asyncio.Task[None] | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._status: dict[str, Any] = {}
        self.on_status: StatusCallback | None = None
        self.on_event: EventCallback | None = None
        self.on_disconnect: DisconnectCallback | None = None

    @property
    def url(self) -> str:
        """WebSocket endpoint of the device."""
        return f"wss://{self._host}/ws"

    @property
    def connected(self) -> bool:
        """Whether the socket is open."""
        return self._ws is not None and not self._ws.closed

    @property
    def status(self) -> dict[str, Any]:
        """The cached Status tree (without the top-level ``Status`` key)."""
        return self._status

    async def connect(self) -> dict[str, Any]:
        """Open the socket, load Status and subscribe to feedback."""
        try:
            self._ws = await self._session.ws_connect(
                self.url,
                headers=self._headers,
                heartbeat=HEARTBEAT,
                timeout=aiohttp.ClientWSTimeout(ws_close=10),
            )
        except aiohttp.WSServerHandshakeError as err:
            if err.status in (401, 403):
                raise RoomOSAuthError("Invalid username or password") from err
            raise RoomOSConnectionError(
                f"WebSocket handshake failed ({err.status}); is "
                "NetworkServices WebSocket enabled on the device?"
            ) from err
        except (aiohttp.ClientError, TimeoutError, OSError) as err:
            raise RoomOSConnectionError(f"Cannot reach {self._host}: {err}") from err

        self._reader = asyncio.create_task(self._read_loop())
        try:
            result = await self.request("xGet", {"Path": ["Status"]})
            if isinstance(result, dict) and set(result) == {"Status"}:
                result = result["Status"]
            self._status = result if isinstance(result, dict) else {}
            await self.request(
                "xFeedback/Subscribe",
                {"Query": ["Status"], "NotifyCurrentValue": False},
            )
            await self.request(
                "xFeedback/Subscribe",
                {"Query": ["Event"], "NotifyCurrentValue": False},
            )
        except RoomOSError:
            await self.close()
            raise
        return self._status

    async def close(self) -> None:
        """Close the socket and stop the reader."""
        ws, self._ws = self._ws, None
        if ws is not None and not ws.closed:
            await ws.close()
        if self._reader is not None:
            reader, self._reader = self._reader, None
            if reader is not asyncio.current_task():
                reader.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await reader
        self._fail_pending(RoomOSConnectionError("Connection closed"))

    async def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send one JSON-RPC request and wait for its result."""
        if not self.connected:
            raise RoomOSConnectionError("Not connected")
        assert self._ws is not None
        request_id = next(self._ids)
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._ws.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params or {},
                }
            )
            async with asyncio.timeout(REQUEST_TIMEOUT):
                response = await future
        except TimeoutError as err:
            raise RoomOSConnectionError(f"{method} timed out") from err
        except (aiohttp.ClientError, ConnectionError) as err:
            raise RoomOSConnectionError(f"{method} failed: {err}") from err
        finally:
            self._pending.pop(request_id, None)
        if "error" in response:
            raise RoomOSCommandError(method, response["error"])
        return response.get("result")

    async def command(
        self, path: list[str] | str, params: dict[str, Any] | None = None
    ) -> Any:
        """Run an xCommand, e.g. ``command("Audio Volume Set", {"Level": 30})``."""
        parts = split_path(path)
        if parts and parts[0].lower() == "xcommand":
            parts = parts[1:]
        return await self.request(f"xCommand/{'/'.join(parts)}", params)

    async def get(self, path: list[str] | str) -> Any:
        """Read any xAPI node (Status or Configuration)."""
        return await self.request("xGet", {"Path": split_path(path)})

    async def set(self, path: list[str] | str, value: Any) -> Any:
        """Write a Configuration value."""
        return await self.request("xSet", {"Path": split_path(path), "Value": value})

    async def _read_loop(self) -> None:
        assert self._ws is not None
        ws = self._ws
        error: Exception | None = None
        try:
            async for msg in ws:
                if msg.type is aiohttp.WSMsgType.TEXT:
                    self._handle(msg.json())
                elif msg.type is aiohttp.WSMsgType.ERROR:
                    error = ws.exception() or RoomOSConnectionError("Socket error")
                    break
        except asyncio.CancelledError:
            raise
        except Exception as err:
            error = err
        # Reached when the device closes the socket (reboot, network drop).
        if self._ws is ws:
            self._ws = None
            self._fail_pending(RoomOSConnectionError("Connection lost"))
            if self.on_disconnect is not None:
                self.on_disconnect(error)

    def _handle(self, message: dict[str, Any]) -> None:
        if (request_id := message.get("id")) is not None:
            future = self._pending.get(request_id)
            if future is not None and not future.done():
                future.set_result(message)
            return
        if message.get("method") != "xFeedback/Event":
            return
        params = dict(message.get("params") or {})
        params.pop("Id", None)
        if (
            isinstance(status := params.get("Status"), dict)
            and merge_status(self._status, status)
            and self.on_status is not None
        ):
            self.on_status(self._status)
        if isinstance(event := params.get("Event"), dict) and self.on_event:
            self.on_event(event)

    def _fail_pending(self, error: Exception) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()


def split_path(path: list[str] | str) -> list[str]:
    """Accept ``"Audio Volume Set"``, ``"Audio/Volume/Set"`` or a list."""
    if isinstance(path, str):
        path = path.replace("/", " ").split()
    return [p for p in path if p]

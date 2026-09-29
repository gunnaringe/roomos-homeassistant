"""Fixtures: a fake RoomOS device speaking JSON-RPC over a local WebSocket."""

from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cisco_roomos.api import RoomOSClient, merge_status
from custom_components.cisco_roomos.const import DOMAIN

FIXTURE = Path(__file__).parent / "fixtures" / "desk_mini_status.json"
SERIAL = "FOC0000TEST"
USERNAME = "integrator"
PASSWORD = "secret"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ in every test."""


@pytest.fixture
def expected_lingering_timers() -> bool:
    """aiohttp re-arms the WebSocket heartbeat timer after close() when a
    heartbeat reset was already queued; it fires once and does nothing."""
    return True


@pytest.fixture(autouse=True)
def plain_ws():
    """Talk ws:// to the local fake instead of wss://."""
    with patch.object(
        RoomOSClient, "url", property(lambda self: f"ws://{self._host}/ws")
    ):
        yield


def load_status() -> dict[str, Any]:
    """The scrubbed Desk Mini Status tree."""
    return json.loads(FIXTURE.read_text())


class FakeRoomOS:
    """Minimal RoomOS xAPI: xGet, xSet, xCommand/*, xFeedback/Subscribe."""

    def __init__(self, status: dict[str, Any] | None = None) -> None:
        """Start with the fixture status."""
        self.status = status if status is not None else load_status()
        self.password = PASSWORD
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.errors: dict[str, dict[str, Any]] = {}
        self.results: dict[str, Any] = {}
        self.sockets: list[web.WebSocketResponse] = []
        self.server: TestServer | None = None

    @property
    def host(self) -> str:
        """host:port of the running fake."""
        assert self.server is not None
        return f"127.0.0.1:{self.server.port}"

    def commands(self) -> list[tuple[str, dict[str, Any]]]:
        """Only the xCommand requests."""
        return [(m, p) for m, p in self.requests if m.startswith("xCommand/")]

    async def handle(self, request: web.Request) -> web.StreamResponse:
        """Basic auth, then JSON-RPC over the socket."""
        expected = base64.b64encode(f"{USERNAME}:{self.password}".encode()).decode()
        if request.headers.get("Authorization") != f"Basic {expected}":
            return web.Response(status=401)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.append(ws)
        async for msg in ws:
            if msg.type is not WSMsgType.TEXT:
                continue
            req = msg.json()
            method, params = req["method"], req.get("params") or {}
            self.requests.append((method, params))
            response: dict[str, Any] = {"jsonrpc": "2.0", "id": req["id"]}
            if method in self.errors:
                response["error"] = self.errors[method]
            elif method == "xGet":
                node: Any = {"Status": self.status}
                for key in params["Path"]:
                    node = node[key]
                response["result"] = copy.deepcopy(node)
            elif method == "xFeedback/Subscribe":
                response["result"] = {"Id": len(self.requests)}
            else:
                response["result"] = self.results.get(method, {"status": "OK"})
            await ws.send_json(response)
        self.sockets.remove(ws)
        return ws

    async def push(self, status: dict[str, Any]) -> None:
        """Send a Status feedback fragment to every client."""
        merge_status(self.status, status)
        await self._notify({"Id": 1, "Status": status})

    async def push_event(self, event: dict[str, Any]) -> None:
        """Send an Event feedback to every client."""
        await self._notify({"Id": 2, "Event": event})

    async def _notify(self, params: dict[str, Any]) -> None:
        for ws in list(self.sockets):
            await ws.send_json(
                {"jsonrpc": "2.0", "method": "xFeedback/Event", "params": params}
            )

    async def drop(self) -> None:
        """Close every client socket, as a reboot would."""
        for ws in list(self.sockets):
            await ws.close()


@pytest.fixture
async def device(socket_enabled: None):
    """A running fake device."""
    fake = FakeRoomOS()
    app = web.Application()
    app.router.add_get("/ws", fake.handle)
    fake.server = TestServer(app, host="127.0.0.1")
    await fake.server.start_server()
    yield fake
    await fake.drop()
    await fake.server.close()


def entry_data(host: str) -> dict[str, Any]:
    """Config entry data for a fake device."""
    return {
        CONF_HOST: host,
        CONF_USERNAME: USERNAME,
        CONF_PASSWORD: PASSWORD,
        CONF_VERIFY_SSL: False,
    }


async def setup_device(
    hass: HomeAssistant, fake: FakeRoomOS, serial: str = SERIAL, title: str = "Office"
) -> MockConfigEntry:
    """Add and load a config entry for a fake device."""
    entry = MockConfigEntry(
        domain=DOMAIN, title=title, unique_id=serial, data=entry_data(fake.host)
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry

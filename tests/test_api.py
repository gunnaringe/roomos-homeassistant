"""RoomOS client and Status merging."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from custom_components.cisco_roomos.api import (
    RoomOSAuthError,
    RoomOSClient,
    RoomOSCommandError,
    merge_status,
    split_path,
)

from .conftest import PASSWORD, USERNAME, FakeRoomOS


def test_merge_nested_values() -> None:
    """Scalars overwrite, dicts merge."""
    status = {"Audio": {"Volume": 30, "VolumeMute": "Off"}}
    merge_status(status, {"Audio": {"Volume": 40}})
    assert status == {"Audio": {"Volume": 40, "VolumeMute": "Off"}}


def test_merge_instances_and_ghosts() -> None:
    """List instances merge by id; ghosts remove them."""
    status: dict = {}
    merge_status(status, {"Call": [{"id": 3, "Status": "Dialling"}]})
    merge_status(status, {"Call": [{"id": 3, "Status": "Connected"}]})
    assert status["Call"] == [{"id": 3, "Status": "Connected"}]
    merge_status(status, {"Call": [{"id": 4, "Status": "Ringing"}]})
    merge_status(status, {"Call": [{"id": 3, "ghost": "True"}]})
    assert status["Call"] == [{"id": 4, "Status": "Ringing"}]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("Audio Volume Set", ["Audio", "Volume", "Set"]),
        ("Audio/Volume/Set", ["Audio", "Volume", "Set"]),
        (["Standby", "Activate"], ["Standby", "Activate"]),
    ],
)
def test_split_path(path, expected) -> None:
    """Paths accept spaces, slashes or lists."""
    assert split_path(path) == expected


async def _client(fake: FakeRoomOS, password: str = PASSWORD):
    session = aiohttp.ClientSession()
    return session, RoomOSClient(session, fake.host, USERNAME, password)


async def test_connect_subscribes_and_merges(device: FakeRoomOS) -> None:
    """connect() loads Status, subscribes, and applies feedback."""
    session, client = await _client(device)
    updates: list[dict] = []
    client.on_status = updates.append
    try:
        status = await client.connect()
        assert status["Audio"]["Volume"] == 30
        assert [m for m, _ in device.requests] == [
            "xGet",
            "xFeedback/Subscribe",
            "xFeedback/Subscribe",
        ]
        await device.push({"Audio": {"Volume": 55}})
        await asyncio.sleep(0.05)
        assert client.status["Audio"]["Volume"] == 55
        assert updates
    finally:
        await client.close()
        await session.close()


async def test_command_and_error(device: FakeRoomOS) -> None:
    """xCommand path building and JSON-RPC errors."""
    session, client = await _client(device)
    try:
        await client.connect()
        await client.command("Audio Volume Set", {"Level": 20})
        assert device.requests[-1] == ("xCommand/Audio/Volume/Set", {"Level": 20})
        await client.command("xCommand Standby Activate")
        assert device.requests[-1][0] == "xCommand/Standby/Activate"
        device.errors["xCommand/Dial"] = {
            "code": 1,
            "message": "Command returned an error.",
            "data": {"Reason": "No number"},
        }
        with pytest.raises(RoomOSCommandError, match="No number"):
            await client.command("Dial", {})
    finally:
        await client.close()
        await session.close()


async def test_bad_password(device: FakeRoomOS) -> None:
    """401 on the handshake is an auth error."""
    session, client = await _client(device, password="wrong")
    try:
        with pytest.raises(RoomOSAuthError):
            await client.connect()
    finally:
        await session.close()


async def test_disconnect_callback(device: FakeRoomOS) -> None:
    """The device closing the socket is reported once."""
    session, client = await _client(device)
    lost: list = []
    client.on_disconnect = lost.append
    try:
        await client.connect()
        await device.drop()
        await asyncio.sleep(0.05)
        assert len(lost) == 1
        assert not client.connected
    finally:
        await client.close()
        await session.close()

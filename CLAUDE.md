# roomos-homeassistant

Home Assistant custom integration (`cisco_roomos`) for Cisco RoomOS devices,
installed through HACS as a custom repository. Primarily developed by Claude.

## Shape

- `api.py` — `RoomOSClient`: one JSON-RPC 2.0 session over `wss://<host>/ws`
  with a Basic auth header. `connect()` = `xGet Status` + `xFeedback/Subscribe`
  for `Status` and `Event`. Feedback fragments are merged into the cached tree
  by `merge_status` (multi-instance nodes are lists keyed by `id`; `ghost`
  removes an instance). All wire handling lives here — entities never build
  JSON-RPC by hand, they call `client.command("Audio Volume Set", {...})`.
- `coordinator.py` — `DataUpdateCoordinator` with `update_interval=None`; data
  is pushed from the client callbacks. Owns reconnect (exponential backoff,
  reauth on 401) and fires `cisco_roomos_event` for xAPI events.
- `entity.py` — device info, `value_at("A.B.C")` (lists resolve to their first
  instance), `as_number` (maps `Unavailable`/`-1` to None), `is_value`, and
  `RoomOSEntityDescription.exists_path/exists_fn` so entities are only created
  for nodes the device reports.
- Platforms are description tables: add an entity by adding a description with
  a `value_fn`/`is_on_fn` and a `translation_key`, then the name in
  `strings.json` **and** `translations/en.json` (keep them identical), and an
  icon in `icons.json`. Don't add other translations — entity IDs are
  generated from the system language and the user wants them in English.
- `bookings.py` — parses `Bookings List` into `Meeting`s. The coordinator
  keeps `meetings` (refreshed at start, every 5 min, on `Bookings` events and
  after reconnect); calendar, next-meeting sensor and join button read it.
  They exist only when the Status tree has `Bookings`.
- `media_player.py` — standby = off, active call = playing.
- `services.py` — `command`, `set_configuration`, `dial`, all targeting a
  `device_id`. One entry per device; unique ID = serial number.

## Conventions

- No runtime requirements (`manifest.json` `requirements: []`).
- aiohttp's WebSocket heartbeat can re-arm a timer after close; tests allow
  lingering timers for that reason (`expected_lingering_timers` in conftest).
- Fixture `tests/fixtures/desk_mini_status.json` is scrubbed real data — keep
  personal identifiers (serials, MACs, SIP URIs, names, numbers) out of it; the
  repo is public.
- Release: bump `manifest.json` `version`, tag `vX.Y.Z`, push the tag; the
  release workflow checks they match and creates the GitHub release HACS installs.

## Checks

```sh
mise run lint && mise run test
podman run --rm -v "$PWD:/github/workspace:ro" ghcr.io/home-assistant/hassfest:latest
```

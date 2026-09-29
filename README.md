# Cisco RoomOS for Home Assistant

Local-push Home Assistant integration for Cisco collaboration devices running
RoomOS — Desk, Desk Mini, Desk Pro, Board, Room Bar, Room Kit and friends.

It keeps one WebSocket open to each device's xAPI, loads the full `Status`
tree once and then applies change notifications (`xFeedback`) as they arrive.
No polling: calls, mute, standby, presence and room analytics update
instantly. No extra Python packages either — it uses the aiohttp client that
ships with Home Assistant.

Add as many devices as you like; each one is its own config entry and device.

## Prepare the device

1. **WebSocket API.** Must be enabled — it is by default on current RoomOS
   (`xConfiguration NetworkServices Websocket: FollowHTTPService`). HTTPS must
   be on as well (`NetworkServices HTTP Mode: HTTPS` or `HTTP+HTTPS`).
2. **A local user.** In the device's web interface go to *Users* and create a
   user for Home Assistant with the **Integrator** role (enough for status,
   mute, volume, standby and calls). Restarting the device from Home Assistant
   needs **Admin**. Avoid reusing the main `admin` account.

## Install

### HACS

1. HACS → ⋮ → **Custom repositories** → add
   `https://github.com/gunnaringe/roomos-homeassistant`, category **Integration**.
2. Install **Cisco RoomOS** and restart Home Assistant.
3. **Settings → Devices & services → Add integration → Cisco RoomOS.**

### Manual

Copy `custom_components/cisco_roomos` into your `config/custom_components/`
and restart.

## Setup

| Field | |
| --- | --- |
| Host | IP address or hostname of the device |
| Username / Password | The local user from above |
| Verify SSL certificate | Off by default — devices ship with a self-signed certificate |

The device's serial number identifies the entry, so adding the same device
twice just updates its address. Change host or credentials later with
**Reconfigure**; if the password stops working you get a re-authentication
prompt.

## Entities

Entities are only created for what the device actually reports — e.g. the
air quality sensor only shows up on devices with that sensor.

| Platform | Entity | Source |
| --- | --- | --- |
| Sensor | Temperature, Humidity | `RoomAnalytics` |
| Sensor | Air quality index | `RoomAnalytics.AirQuality.Index` (Navigator, Board Pro, ...) |
| Sensor | Ambient noise, Sound level | `RoomAnalytics`, dBA |
| Sensor | People count | `RoomAnalytics.PeopleCount.Current` (unknown while counting is inactive) |
| Sensor | Standby state | Awake / Half wake / Entering standby / Standby |
| Sensor | Call status | Idle, Ringing, Connected, ... with remote number, name and direction as attributes |
| Sensor | Webex presence | Signed-in user's presence; custom status as attribute |
| Sensor | Booking availability | Free / FreeUntil / BookedUntil, `until` attribute |
| Sensor | Last boot, Software version, IP address | Diagnostic (IP disabled by default) |
| Binary sensor | In call, Presenting, Screen on | |
| Binary sensor | Room in use, People presence, Close proximity | Occupancy |
| Binary sensor | Camera lid | On when the privacy lid is open |
| Binary sensor | Smoke alarm heard | The device listens for the T3 alarm pattern |
| Binary sensor | Webex registered | Diagnostic |
| Switch | Microphone mute, Speaker mute, Do not disturb, Selfview | Selfview disabled by default |
| Number | Volume | 0–100 |
| Button | Wake, Standby, Half wake, Hang up, Restart | Half wake disabled by default |

## Actions

| Action | Does |
| --- | --- |
| `cisco_roomos.command` | Any xCommand, e.g. `command: Bookings List`, `params: {Limit: 5}`. Returns the device's response. |
| `cisco_roomos.set_configuration` | xConfiguration, e.g. `path: Audio DefaultVolume`, `value: 40` |
| `cisco_roomos.dial` | Call a number or URI, optionally with a protocol |

```yaml
action: cisco_roomos.command
data:
  device_id: 0123456789abcdef
  command: UserInterface Message Alert Display
  params:
    Title: Doorbell
    Text: Someone is at the door
    Duration: 10
```

## Events

Every xAPI event is fired on the Home Assistant bus as `cisco_roomos_event`
with `device_id` and the raw `event` payload — handy for custom UI extension
panels and widgets on the device's touch screen:

```yaml
triggers:
  - trigger: event
    event_type: cisco_roomos_event
    event_data:
      device_id: 0123456789abcdef
conditions:
  - "{{ trigger.event.data.event.UserInterface.Extensions.Panel.Clicked.PanelId == 'lights' }}"
```

## Troubleshooting

- **Cannot connect:** check that `https://<host>/` opens in a browser and that
  the WebSocket setting above is enabled.
- **Entities unavailable:** the socket dropped (reboot, network). The
  integration reconnects on its own with backoff up to a minute.
- **Diagnostics:** the device page has *Download diagnostics*; serials, MACs,
  names and addresses are redacted.

## Development

```sh
mise install
uv sync
mise run lint
mise run test
```

Tests run against a fake device speaking JSON-RPC over a local WebSocket
(`tests/conftest.py`), seeded from a scrubbed Desk Mini status tree.

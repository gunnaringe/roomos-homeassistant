"""Parse ``xCommand Bookings List`` results into meetings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util


@dataclass(frozen=True, slots=True)
class Meeting:
    """One booking the device knows about."""

    booking_id: str
    title: str
    start: datetime
    end: datetime
    organizer: str | None
    private: bool
    number: str | None
    protocol: str | None

    @property
    def joinable(self) -> bool:
        """Whether there is something to dial."""
        return bool(self.number)

    def as_dict(self) -> dict[str, Any]:
        """Attribute-friendly form."""
        return {
            "title": self.title,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "organizer": self.organizer,
            "joinable": self.joinable,
        }


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def parse_bookings(result: Any) -> list[Meeting]:
    """Meetings sorted by start; malformed entries are skipped."""
    meetings: list[Meeting] = []
    for booking in _as_list(
        result.get("Booking") if isinstance(result, dict) else None
    ):
        if not isinstance(booking, dict):
            continue
        time = booking.get("Time") or {}
        start = dt_util.parse_datetime(str(time.get("StartTime") or ""))
        end = dt_util.parse_datetime(str(time.get("EndTime") or ""))
        if start is None or end is None:
            continue
        organizer = booking.get("Organizer") or {}
        name = " ".join(
            p for p in (organizer.get("FirstName"), organizer.get("LastName")) if p
        )
        call = next(
            (
                c
                for c in _as_list(
                    (booking.get("DialInfo") or {}).get("Calls", {}).get("Call")
                )
                if isinstance(c, dict) and c.get("Number")
            ),
            {},
        )
        private = str(booking.get("Privacy", "")).lower() == "private"
        meetings.append(
            Meeting(
                booking_id=str(booking.get("Id") or booking.get("id") or ""),
                title=str(
                    booking.get("Title")
                    or ("Private meeting" if private else "Meeting")
                ),
                start=dt_util.as_utc(start),
                end=dt_util.as_utc(end),
                organizer=name or organizer.get("Email") or None,
                private=private,
                number=call.get("Number"),
                protocol=call.get("Protocol"),
            )
        )
    return sorted(meetings, key=lambda m: m.start)


def next_meeting(
    meetings: list[Meeting], now: datetime | None = None
) -> Meeting | None:
    """The meeting in progress, else the next one to start."""
    now = now or dt_util.utcnow()
    return next((m for m in meetings if m.end > now), None)

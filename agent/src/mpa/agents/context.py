"""What the orchestrator knows about the meeting before the sub-agents start."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from mpa.contract import CalendarEvent

AGENT_NAMES = ("correspondence", "documents", "news", "attendees")
GAP_SOURCE = {
    "correspondence": "email",
    "documents": "docs",
    "news": "news",
    "attendees": "contacts",
}
AGENT_LABEL = {
    "correspondence": "Correspondence (email and chat)",
    "documents": "Documents",
    "news": "News",
    "attendees": "Attendee information",
}
# Which briefing sections each agent's outage or cut-off must be announced in.
AGENT_SECTIONS: dict[str, tuple[str, ...]] = {
    "correspondence": ("where_we_left_off", "open_items"),
    "documents": ("client_snapshot",),
    "news": ("recent_news",),
    "attendees": ("attendees",),
}


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    organization: str
    role: str
    is_user: bool = False

    def line(self) -> str:
        if not self.organization:
            return f"{self.id} ({self.name})"
        who = f"{self.id} {self.name}, {self.role}, {self.organization}"
        return who + (" (the user)" if self.is_user else "")


@dataclass(frozen=True)
class MeetingContext:
    client: str
    meeting: CalendarEvent
    people: tuple[Person, ...]
    now: datetime

    @property
    def user(self) -> Person | None:
        return next((p for p in self.people if p.is_user), None)

    @property
    def when(self) -> str:
        return format_when(self.meeting.start, self.meeting.end)


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def format_when(start: str, end: str) -> str:
    s, e = parse_ts(start), parse_ts(end)
    return f"{s:%A} {s.day} {s:%B %Y}, {s:%H:%M}-{e:%H:%M} UTC"

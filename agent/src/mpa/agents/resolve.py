"""Turn the user's request into one calendar meeting and its client, by deterministic rules."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import timedelta

from mpa.agents.context import MeetingContext, Person, format_when, parse_ts
from mpa.contract import CalendarEvent, DataSource, DataSourceError, Settings

WINDOW_DAYS = 14
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_ABBREV = {"mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3, "fri": 4}
_LEGAL = {"ltd", "limited", "inc", "plc", "llc", "gmbh", "co", "group"}


@dataclass
class Resolution:
    context: MeetingContext | None = None
    problem: str | None = None
    client: str | None = None
    candidates: list[str] = field(default_factory=list)


def norm(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", text.lower().replace("&", " and ")).strip() + " "


def client_of(event: CalendarEvent) -> str:
    return event.title.split(" - ")[0].strip() if " - " in event.title else event.title.strip()


def aliases(client: str, all_clients: list[str]) -> list[str]:
    words = [w for w in norm(client).split() if w not in _LEGAL]
    names = {norm(client), " " + " ".join(words) + " "}
    first = words[0] if words else ""
    others = [c for c in all_clients if c != client]
    if len(first) >= 4 and not any(first in norm(o).split() for o in others):
        names.add(f" {first} ")
    return sorted(names, key=len, reverse=True)


_NAME = re.compile(r"\b(?:with|for)\s+((?:[A-Z][\w&.'-]*(?:\s+|$)){1,4})")
_NOT_NAMES = {
    *("me", "my", "the", "a", "an", "our", "this", "next", "tomorrow", "today", "i", "us"),
    *_WEEKDAYS,
}


def unknown_client(message: str) -> str | None:
    """A capitalised name after 'with' or 'for' that is not a weekday or a pronoun."""
    for m in _NAME.finditer(message):
        words = m.group(1).split()
        while words and words[-1].lower().strip(".,") in _NOT_NAMES:
            words.pop()
        if words and words[0].lower() not in _NOT_NAMES:
            return " ".join(words).strip(".,")
    return None


def mentioned_weekday(message: str) -> int | None:
    text = norm(message).split()
    for w in text:
        if w in _WEEKDAYS:
            return _WEEKDAYS.index(w)
        if w in _ABBREV:
            return _ABBREV[w]
    return None


async def _calendar(data: DataSource, settings: Settings) -> list[CalendarEvent]:
    start, end = settings.demo_now, settings.demo_now + timedelta(days=WINDOW_DAYS)
    try:
        return await data.get_calendar(start=start, end=end)
    except DataSourceError:
        await asyncio.sleep(0.25)
        return await data.get_calendar(start=start, end=end)


async def _people(data: DataSource, event: CalendarEvent) -> tuple[Person, ...]:
    async def one(pid: str) -> Person:
        try:
            c = await data.get_contact(pid)
        except (KeyError, DataSourceError):
            return Person(pid, pid, "", "")
        return Person(c.id, c.name, c.organization, c.role, c.is_user)

    people = await asyncio.gather(
        *(one(p) for p in sorted(event.attendees, key=lambda p: int(p[1:])))
    )
    return tuple(people)


async def resolve_meeting(message: str, data: DataSource, settings: Settings) -> Resolution:
    now = settings.demo_now
    try:
        events = await _calendar(data, settings)
    except DataSourceError:
        return Resolution(
            problem="The calendar could not be reached, so no meeting was identified."
        )
    events = sorted((e for e in events if parse_ts(e.start) >= now), key=lambda e: (e.start, e.id))
    if not events:
        return Resolution(problem=f"No meetings are scheduled in the next {WINDOW_DAYS} days.")

    clients = sorted({client_of(e) for e in events})
    padded = norm(message)
    matched = [c for c in clients if any(a in padded for a in aliases(c, clients))]
    weekday = mentioned_weekday(message)
    pool = events
    if matched:
        pool = [e for e in pool if client_of(e) in matched]
    if weekday is not None:
        pool = [e for e in pool if parse_ts(e.start).weekday() == weekday]

    label = ", ".join(matched) if matched else None
    day = _WEEKDAYS[weekday].capitalize() if weekday is not None else None
    if not pool:
        if label and day:
            nxt = [e for e in events if client_of(e) in matched]
            hint = (
                f" Their next meeting is {nxt[0].title} on {format_when(nxt[0].start, nxt[0].end)}."
                if nxt
                else ""
            )
            return Resolution(
                problem=f"No meeting with {label} on {day} was found.{hint}", client=label
            )
        if label:
            return Resolution(problem=f"No upcoming meeting with {label} was found.", client=label)
        return Resolution(problem=f"No meeting on {day} was found in the next {WINDOW_DAYS} days.")
    if not matched and len({client_of(e) for e in pool}) > 1:
        listed = [f"{e.title} ({format_when(e.start, e.end)})" for e in pool]
        if (name := unknown_client(message)) is not None:
            return Resolution(
                problem=f"No upcoming meeting with {name} was found in the calendar.",
                candidates=listed,
            )
        return Resolution(
            problem="The request does not say which client; several meetings fit.",
            candidates=listed,
        )
    event = pool[0]
    people = await _people(data, event)
    return Resolution(
        context=MeetingContext(client_of(event), event, people, now), client=client_of(event)
    )

"""FakeDataSource: the committed fake dataset in data/ behind the DataSource protocol."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from mpa.contract import (
    CalendarEvent,
    ChatMessage,
    CitationType,
    Contact,
    Doc,
    Email,
    NewsItem,
    SearchHit,
    SourceItem,
)
from mpa.data.index import BM25Index
from mpa.data.loader import load_jsonl
from mpa.data.text import make_snippet, shorten, tokenise, weighted

MAX_LIMIT = 10
TITLE_CHARS = 200
# Enron noise is real but unrelated text; a fixed discount keeps it below synthetic matches
# of similar strength while still letting a strong exact match through.
ENRON_WEIGHT = 0.5

HitType = Literal["email", "chat", "doc", "news", "contact", "cal"]


def _to_hit(type_: HitType, id_: str, title: str, snippet: str, score: float) -> SearchHit:
    return SearchHit.model_validate(
        {
            "type": type_,
            "id": id_,
            "title": shorten(title, TITLE_CHARS),
            "snippet": snippet,
            "score": round(score, 4),
        }
    )


class _Collection[T: BaseModel]:
    """Items of one type plus a lazily built, cached BM25 index."""

    def __init__(
        self,
        items: Sequence[T],
        type_: HitType,
        tokens: Callable[[T], list[str]],
        title: Callable[[T], str],
        text: Callable[[T], str],
        multiplier: Callable[[T], float] = lambda _: 1.0,
        entity: Callable[[T], str] = lambda _: "",
    ) -> None:
        self.items = list(items)
        self.by_id: dict[str, T] = {getattr(i, "id"): i for i in self.items}  # noqa: B009
        self._type = type_
        self._tokens, self._title, self._text, self._mult = tokens, title, text, multiplier
        self._entity = entity
        self._index: BM25Index | None = None

    def search(self, query: str, limit: int) -> list[SearchHit]:
        if self._index is None:
            self._index = BM25Index(
                list(self.by_id),
                [self._tokens(i) for i in self.items],
                [self._mult(i) for i in self.items],
                [frozenset(tokenise(self._entity(i))) for i in self.items],
            )
        ranked, terms = self._index.search(query, min(max(limit, 0), MAX_LIMIT))
        return [
            _to_hit(
                self._type,
                id_,
                self._title(self.by_id[id_]),
                make_snippet(self._text(self.by_id[id_]), terms),
                score,
            )
            for id_, score in ranked
        ]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _when(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


class FakeDataSource:
    def __init__(self, data_dir: Path) -> None:
        emails = load_jsonl(data_dir, "emails", Email)
        chats = load_jsonl(data_dir, "chats", ChatMessage)
        docs = load_jsonl(data_dir, "docs", Doc)
        events = load_jsonl(data_dir, "calendar", CalendarEvent)
        contacts = load_jsonl(data_dir, "contacts", Contact)
        news = load_jsonl(data_dir, "news", NewsItem)

        self._contacts = _Collection(
            contacts,
            "contact",
            lambda c: weighted(
                (c.name, 3),
                (c.organization, 2),
                (c.role, 2),
                (c.notes, 1),
                (c.email.split("@")[0], 1),
            ),
            lambda c: c.name,
            lambda c: f"{c.role}, {c.organization}. {c.notes}",
        )
        self._calendar = _Collection(
            events,
            "cal",
            lambda e: weighted((e.title, 3), (e.description, 1), (self._names(e.attendees), 1)),
            lambda e: e.title,
            lambda e: e.description,
        )
        self._emails = _Collection(
            emails,
            "email",
            lambda e: weighted(
                (e.subject, 3),
                (e.sender.split("@")[0], 1),
                (" ".join(a.split("@")[0] for a in [*e.to, *e.cc]), 1),
                (e.body, 1),
            ),
            lambda e: e.subject,
            lambda e: e.body,
            lambda e: ENRON_WEIGHT if e.origin == "enron" else 1.0,
        )
        self._chats = _Collection(
            chats,
            "chat",
            lambda c: weighted((c.channel, 2), (c.author, 1), (c.text, 1)),
            lambda c: f"{c.channel} · {c.author}",
            lambda c: c.text,
        )
        self._docs = _Collection(
            docs,
            "doc",
            lambda d: weighted((d.title, 3), (d.kind, 1), (d.author, 1), (d.body, 1)),
            lambda d: d.title,
            lambda d: d.body,
        )
        self._news = _Collection(
            news,
            "news",
            lambda n: weighted((n.title, 3), (n.about or "", 2), (n.source, 1), (n.body, 1)),
            lambda n: n.title,
            lambda n: n.body,
            entity=lambda n: n.about or "",
        )

    def _names(self, contact_ids: Sequence[str]) -> str:
        return " ".join(
            self._contacts.by_id[p].name for p in contact_ids if p in self._contacts.by_id
        )

    @staticmethod
    def _get[T: BaseModel](collection: _Collection[T], id: str) -> T:
        try:
            return collection.by_id[id]
        except KeyError:
            raise KeyError(id) from None

    async def search_email(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        return self._emails.search(query, limit)

    async def get_email(self, id: str) -> Email:
        return self._get(self._emails, id)

    async def search_chat(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        return self._chats.search(query, limit)

    async def get_chat(self, id: str) -> ChatMessage:
        return self._get(self._chats, id)

    async def search_docs(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        return self._docs.search(query, limit)

    async def get_doc(self, id: str) -> Doc:
        return self._get(self._docs, id)

    async def get_calendar(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        query: str | None = None,
    ) -> list[CalendarEvent]:
        """Events overlapping [start, end); with `query`, events matching any query term,
        best match first (ties by start time), otherwise chronological."""
        lo = _utc(start) if start else None
        hi = _utc(end) if end else None
        terms = set(tokenise(query)) if query else set()
        scored: list[tuple[int, datetime, CalendarEvent]] = []
        for event in self._calendar.items:
            begins, finishes = _when(event.start), _when(event.end)
            if (lo and finishes <= lo) or (hi and begins >= hi):
                continue
            matched = 0
            if query is not None and terms:
                haystack = set(
                    weighted(
                        (event.title, 1),
                        (event.description, 1),
                        (self._names(event.attendees), 1),
                    )
                )
                matched = len(terms & haystack)
                if not matched:
                    continue
            scored.append((matched, begins, event))
        scored.sort(key=lambda t: (-t[0], t[1], t[2].id))
        return [event for _, _, event in scored]

    async def search_news(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        return self._news.search(query, limit)

    async def get_news(self, id: str) -> NewsItem:
        return self._get(self._news, id)

    async def get_contact(self, id: str) -> Contact:
        return self._get(self._contacts, id)

    async def find_contacts(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        return self._contacts.search(query, limit)

    async def get_source(self, type: CitationType, id: str) -> SourceItem:
        item: Email | ChatMessage | Doc | CalendarEvent | Contact | NewsItem
        match type:
            case "email":
                item = self._get(self._emails, id)
            case "chat":
                item = self._get(self._chats, id)
            case "doc":
                item = self._get(self._docs, id)
            case "news":
                item = self._get(self._news, id)
            case "contact":
                item = self._get(self._contacts, id)
            case "cal":
                item = self._get(self._calendar, id)
            case _:
                raise KeyError(id)
        return SourceItem(item)


__all__ = ["ENRON_WEIGHT", "FakeDataSource"]

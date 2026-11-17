"""Fault injection: a DataSource wrapper that makes chosen sources unavailable."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from mpa.contract import (
    CalendarEvent,
    ChatMessage,
    CitationType,
    Contact,
    DataSource,
    DataSourceError,
    Doc,
    Email,
    NewsItem,
    SearchHit,
    SourceItem,
)

FailSource = Literal["news", "email", "docs", "all"]

_FAILS: dict[str, frozenset[str]] = {
    "news": frozenset({"news"}),
    "email": frozenset({"email", "chat"}),
    "docs": frozenset({"doc"}),
    "all": frozenset({"email", "chat", "doc", "news", "contact", "cal"}),
}
_LABEL = {
    "news": "news",
    "email": "email",
    "chat": "chat",
    "doc": "documents",
    "contact": "contacts",
    "cal": "calendar",
}


class InjectedFault(DataSourceError):
    """A DataSourceError raised on purpose; the loop reports it as `fault_injected`."""

    injected = True


class FaultInjectingDataSource:
    def __init__(self, inner: DataSource, fail_source: FailSource | None) -> None:
        self._inner = inner
        self.fail_source = fail_source
        self._down = _FAILS.get(fail_source or "", frozenset())

    def _check(self, kind: str) -> None:
        if kind in self._down:
            raise InjectedFault(f"{_LABEL[kind]} source unavailable (injected fault)")

    async def search_email(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        self._check("email")
        return await self._inner.search_email(query, limit=limit)

    async def get_email(self, id: str) -> Email:
        self._check("email")
        return await self._inner.get_email(id)

    async def search_chat(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        self._check("chat")
        return await self._inner.search_chat(query, limit=limit)

    async def get_chat(self, id: str) -> ChatMessage:
        self._check("chat")
        return await self._inner.get_chat(id)

    async def search_docs(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        self._check("doc")
        return await self._inner.search_docs(query, limit=limit)

    async def get_doc(self, id: str) -> Doc:
        self._check("doc")
        return await self._inner.get_doc(id)

    async def get_calendar(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        query: str | None = None,
    ) -> list[CalendarEvent]:
        self._check("cal")
        return await self._inner.get_calendar(start=start, end=end, query=query)

    async def search_news(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        self._check("news")
        return await self._inner.search_news(query, limit=limit)

    async def get_news(self, id: str) -> NewsItem:
        self._check("news")
        return await self._inner.get_news(id)

    async def get_contact(self, id: str) -> Contact:
        self._check("contact")
        return await self._inner.get_contact(id)

    async def find_contacts(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        self._check("contact")
        return await self._inner.find_contacts(query, limit=limit)

    async def get_source(self, type: CitationType, id: str) -> SourceItem:
        self._check(type)
        return await self._inner.get_source(type, id)

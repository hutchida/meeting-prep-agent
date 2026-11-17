"""GraphDataSource: placeholder for a live Microsoft 365 / Microsoft Graph backend."""

from __future__ import annotations

from datetime import datetime
from typing import NoReturn

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

_MESSAGE = "GraphDataSource is a design stub: use DATA_SOURCE=snapshot (FakeDataSource)"


def _todo() -> NoReturn:
    raise NotImplementedError(_MESSAGE)


class GraphDataSource:
    """Intended mapping of the DataSource protocol onto Microsoft Graph (not implemented).

    Access is strictly read-only and uses delegated permissions only (the signed-in user's own
    data, never application permissions). No write scope (`*.ReadWrite`, `Mail.Send`, ...) is
    ever requested, matching the read-only tool list the agents are given.

    Mapping (method: Graph resource, delegated scope):

    - search_email / get_email: `GET /me/messages?$search=...` and `/me/messages/{id}`;
      `Mail.Read`.
    - search_chat / get_chat: `GET /me/chats/{id}/messages` and Teams channel messages;
      `Chat.Read`, `ChatMessage.Read`.
    - search_docs / get_doc: `POST /search/query` (driveItem) and
      `/me/drive/items/{id}/content`; `Files.Read.All`.
    - get_calendar: `GET /me/calendarView?startDateTime=&endDateTime=`; `Calendars.Read`.
    - get_contact / find_contacts: `GET /me/people?$search=...` and `/me/contacts`;
      `People.Read`, `Contacts.Read`.
    - search_news / get_news: not part of Graph; a web-search provider behind the same
      interface (its own API key, no Microsoft scope).

    Ids: Graph ids are long opaque strings, so an adapter would keep a stable mapping from them to
    the contract's short ids (`E123`, `C9`, ...) used in citations.

    Pagination: follow `@odata.nextLink` until `limit` items are collected (never fetch more than
    needed), and request only needed fields with `$select` and `$top`.

    Throttling and failures: on HTTP 429 or 503 honour the `Retry-After` header (bounded wait),
    then raise `DataSourceError` so the agent loop's retry/backoff and `subagent_failed` handling
    apply. 404 for an item maps to `KeyError`; 401/403 raise `DataSourceError` without echoing
    tokens, URLs or response bodies.

    Content is untrusted: bodies are returned as data and truncated to the contract limits.
    """

    async def search_email(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        _todo()

    async def get_email(self, id: str) -> Email:
        _todo()

    async def search_chat(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        _todo()

    async def get_chat(self, id: str) -> ChatMessage:
        _todo()

    async def search_docs(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        _todo()

    async def get_doc(self, id: str) -> Doc:
        _todo()

    async def get_calendar(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        query: str | None = None,
    ) -> list[CalendarEvent]:
        _todo()

    async def search_news(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        _todo()

    async def get_news(self, id: str) -> NewsItem:
        _todo()

    async def get_contact(self, id: str) -> Contact:
        _todo()

    async def find_contacts(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        _todo()

    async def get_source(self, type: CitationType, id: str) -> SourceItem:
        _todo()

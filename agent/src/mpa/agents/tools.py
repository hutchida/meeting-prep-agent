"""Read-only tools built on the DataSource. Nothing here can send, write or delete."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from mpa.contract import DataSource, ToolSpec
from mpa.loop.runner import SUBMIT
from mpa.loop.tools import Tool, ToolRegistry

ALLOWED_TOOL_NAMES = frozenset(
    {
        "search_email",
        "get_email",
        "search_chat",
        "get_chat",
        "search_docs",
        "get_doc",
        "search_news",
        "get_news",
        "get_calendar",
        "get_contact",
        "find_contacts",
        SUBMIT,
    }
)
AGENT_TOOLS: dict[str, tuple[str, ...]] = {
    "correspondence": ("search_email", "get_email", "search_chat", "get_chat"),
    "documents": ("search_docs", "get_doc"),
    "news": ("search_news", "get_news"),
    "attendees": ("get_calendar", "get_contact", "find_contacts"),
}
DEFAULT_LIMIT = 6


def _search_spec(name: str, what: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"Search {what}. Returns short snippets; use get_* to read an item in full.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keywords, e.g. a name and a topic."},
                "limit": {
                    "type": "integer",
                    "description": f"Max results, 1-10 (default {DEFAULT_LIMIT}).",
                },
            },
            "required": ["query"],
        },
    )


def _get_spec(name: str, what: str, example: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"Read one {what} in full by id.",
        parameters={
            "type": "object",
            "properties": {"id": {"type": "string", "description": f"For example {example}"}},
            "required": ["id"],
        },
    )


def _query(args: dict[str, Any]) -> str:
    q = args.get("query")
    if not isinstance(q, str) or not q.strip():
        raise ValueError("query must be a non-empty string")
    return q.strip()[:200]


def _limit(args: dict[str, Any]) -> int:
    raw = args.get("limit", DEFAULT_LIMIT)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ValueError("limit must be an integer")
    return max(1, min(10, int(raw)))


def _id(args: dict[str, Any]) -> str:
    i = args.get("id")
    if not isinstance(i, str) or not i.strip():
        raise ValueError("id must be a non-empty string")
    return i.strip()


def _when(value: Any, name: str) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def build_tools(data: DataSource) -> dict[str, Tool]:
    def search(fn: Callable[..., Awaitable[Any]]) -> Callable[[dict[str, Any]], Awaitable[Any]]:
        async def handler(args: dict[str, Any]) -> Any:
            return await fn(_query(args), limit=_limit(args))

        return handler

    def get(fn: Callable[[str], Awaitable[Any]]) -> Callable[[dict[str, Any]], Awaitable[Any]]:
        async def handler(args: dict[str, Any]) -> Any:
            return await fn(_id(args))

        return handler

    async def get_calendar(args: dict[str, Any]) -> Any:
        query = args.get("query")
        return await data.get_calendar(
            start=_when(args.get("start"), "start"),
            end=_when(args.get("end"), "end"),
            query=query.strip() if isinstance(query, str) and query.strip() else None,
        )

    calendar_spec = ToolSpec(
        name="get_calendar",
        description="List calendar events, optionally filtered by text and/or a time window.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text to match in title or description.",
                },
                "start": {"type": "string", "description": "ISO-8601 UTC, events from this time."},
                "end": {"type": "string", "description": "ISO-8601 UTC, events until this time."},
            },
        },
    )
    return {
        t.spec.name: t
        for t in [
            Tool(_search_spec("search_email", "emails"), search(data.search_email)),
            Tool(_get_spec("get_email", "email", "E51"), get(data.get_email)),
            Tool(_search_spec("search_chat", "chat messages"), search(data.search_chat)),
            Tool(_get_spec("get_chat", "chat message", "C26"), get(data.get_chat)),
            Tool(_search_spec("search_docs", "documents"), search(data.search_docs)),
            Tool(_get_spec("get_doc", "document", "D7"), get(data.get_doc)),
            Tool(_search_spec("search_news", "news articles"), search(data.search_news)),
            Tool(_get_spec("get_news", "news article", "N26"), get(data.get_news)),
            Tool(calendar_spec, get_calendar),
            Tool(_get_spec("get_contact", "contact", "P8"), get(data.get_contact)),
            Tool(
                _search_spec("find_contacts", "contacts by name, role or organisation"),
                search(data.find_contacts),
            ),
        ]
    }


def build_registry(agent: str, data: DataSource) -> ToolRegistry:
    tools = build_tools(data)
    return ToolRegistry(tools[name] for name in AGENT_TOOLS[agent])


def all_tool_names(data: DataSource) -> set[str]:
    """Every tool name any agent can call, plus the terminal tool (used by the allow-list test)."""
    names = {n for agent in AGENT_TOOLS for n in build_registry(agent, data).names}
    return names | {SUBMIT}

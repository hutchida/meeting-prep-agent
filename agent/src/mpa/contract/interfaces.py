"""Cross-task interfaces (see docs/orchestration/interfaces.md). Service code imports these and
must not change them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from mpa.contract.models import (
    CalendarEvent,
    ChatMessage,
    Contact,
    Doc,
    Email,
    NewsItem,
    SearchHit,
    SourceItem,
)
from mpa.contract.settings import Settings

CitationType = Literal["email", "chat", "doc", "news", "contact", "cal"]


# ---------------------------------------------------------------- LLM
class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class LLMMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None  # assistant only
    tool_call_id: str | None = None  # tool only
    name: str | None = None  # tool only


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


class LLMResponse(BaseModel):
    message: LLMMessage
    usage: Usage
    model: str
    finish_reason: str | None = None
    latency_ms: int = 0


class LLMClient(Protocol):
    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tag: str | None = None,  # logical label, e.g. "news:step2"; NOT part of the replay key
    ) -> LLMResponse: ...


# ---------------------------------------------------------------- data
class DataSource(Protocol):
    # All methods async. Search methods return at most `limit` (<= 10) SearchHit, each <= 4 KB.
    async def search_email(self, query: str, *, limit: int = 10) -> list[SearchHit]: ...
    async def get_email(self, id: str) -> Email: ...  # raises KeyError if unknown
    async def search_chat(self, query: str, *, limit: int = 10) -> list[SearchHit]: ...
    async def get_chat(self, id: str) -> ChatMessage: ...
    async def search_docs(self, query: str, *, limit: int = 10) -> list[SearchHit]: ...
    async def get_doc(self, id: str) -> Doc: ...
    async def get_calendar(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        query: str | None = None,
    ) -> list[CalendarEvent]: ...  # time-window and/or text filter
    async def search_news(self, query: str, *, limit: int = 10) -> list[SearchHit]: ...
    async def get_news(self, id: str) -> NewsItem: ...
    async def get_contact(self, id: str) -> Contact: ...
    async def find_contacts(self, query: str, *, limit: int = 10) -> list[SearchHit]: ...
    async def get_source(self, type: CitationType, id: str) -> SourceItem: ...  # GET /sources/..


class DataSourceError(Exception):
    """Raised for transient/unavailable source failures (retryable).

    KeyError means unknown id (not retryable).
    """


# ---------------------------------------------------------------- tracing
# Sync, non-blocking, never raises.
class Span(Protocol):
    def set(self, **attrs: Any) -> None: ...
    def end(self, *, error: str | None = None) -> None: ...


class Tracer(Protocol):
    def start_run(self, run_id: str, *, name: str, input: dict[str, Any]) -> Span: ...
    def start_span(
        self,
        parent: Span,
        name: str,
        *,
        kind: Literal["agent", "step", "tool", "llm"],
        input: Any = None,
    ) -> Span: ...
    def record_llm(
        self, parent: Span, *, model: str, input: Any, output: Any, usage: Usage, latency_ms: int
    ) -> None: ...
    def flush(self) -> None: ...


class NullSpan:
    """Implements `Span` as no-ops."""

    def set(self, **attrs: Any) -> None:
        return None

    def end(self, *, error: str | None = None) -> None:
        return None


class NoopTracer:
    """Implements `Tracer`; used when TRACING=off. Every call is a no-op returning a `NullSpan`."""

    def start_run(self, run_id: str, *, name: str, input: dict[str, Any]) -> Span:
        return NullSpan()

    def start_span(
        self,
        parent: Span,
        name: str,
        *,
        kind: Literal["agent", "step", "tool", "llm"],
        input: Any = None,
    ) -> Span:
        return NullSpan()

    def record_llm(
        self, parent: Span, *, model: str, input: Any, output: Any, usage: Usage, latency_ms: int
    ) -> None:
        return None

    def flush(self) -> None:
        return None


# ---------------------------------------------------------------- run wiring
@dataclass
class RunDeps:
    llm: LLMClient
    data: DataSource
    tracer: Tracer
    settings: Settings

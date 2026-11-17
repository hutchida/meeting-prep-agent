"""Pydantic mirror of the contract in packages/contract (models.py is generated)."""

from mpa.contract import models
from mpa.contract.citations import CitationRef, citation_token, parse_citations
from mpa.contract.limits import LIMITS, LimitError, assert_within_limit, json_bytes
from mpa.contract.models import (
    AgentEvent,
    BriefingPack,
    BriefingRequest,
    CalendarEvent,
    ChatMessage,
    Citation,
    Contact,
    Doc,
    Email,
    EvalResult,
    NewsItem,
    SearchHit,
    SourceItem,
    SubAgentOutput,
    ToolResult,
)

__all__ = [
    "LIMITS",
    "AgentEvent",
    "BriefingPack",
    "BriefingRequest",
    "CalendarEvent",
    "ChatMessage",
    "Citation",
    "CitationRef",
    "Contact",
    "Doc",
    "Email",
    "EvalResult",
    "LimitError",
    "NewsItem",
    "SearchHit",
    "SourceItem",
    "SubAgentOutput",
    "ToolResult",
    "assert_within_limit",
    "citation_token",
    "json_bytes",
    "models",
    "parse_citations",
]

"""LLM client errors. Messages never contain URLs, headers or keys."""

from __future__ import annotations


class LLMError(Exception):
    """A model call failed (after retries). The message is safe to log and to emit in events."""

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class LLMConfigError(LLMError):
    """The live client is not configured; the message names variables, never values."""


class ReplayMiss(LLMError):
    """No recording matches the request. Carries the request hash and the logical tag only."""

    def __init__(self, request_hash: str, tag: str | None) -> None:
        self.request_hash = request_hash
        self.tag = tag
        super().__init__(f"no recording for request {request_hash[:16]} (tag={tag or '-'})")


class RedactionError(LLMError):
    """A recording would have contained a URL, header or key; nothing was written."""

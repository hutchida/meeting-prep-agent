"""Make values safe to send as trace content: bounded size, no URLs, headers or secrets."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

MAX_TRACE_CHARS = 4000
MAX_DEPTH = 6
REDACTED = "[redacted]"

SECRET_ENV_NAMES = (
    "LITELLM_API_KEY",
    "LITELLM_BASE_URL",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_HOST",
)

_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "headers",
        "api_key",
        "apikey",
        "x-api-key",
        "secret",
        "password",
        "base_url",
        "url",
        "host",
    }
)
_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+", re.IGNORECASE)
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_KEYLIKE_RE = re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{8,}")


def secret_values(env: dict[str, str] | None = None) -> tuple[str, ...]:
    source = os.environ if env is None else env
    values = {source.get(name, "").strip() for name in SECRET_ENV_NAMES}
    return tuple(sorted((v for v in values if len(v) >= 6), key=len, reverse=True))


def _scrub_text(text: str, secrets: Iterable[str]) -> str:
    for secret in secrets:
        text = text.replace(secret, REDACTED)
    text = _BEARER_RE.sub(REDACTED, text)
    text = _KEYLIKE_RE.sub(REDACTED, text)
    return _URL_RE.sub("[url]", text)


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in _SENSITIVE_KEYS or lowered.endswith(("_key", "_secret", "_password"))


def _plain(value: Any, secrets: tuple[str, ...], depth: int) -> Any:
    if depth > MAX_DEPTH:
        return "[max depth]"
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, str):
        return _scrub_text(value, secrets)
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, dict):
        return {
            str(k): REDACTED if _is_sensitive_key(str(k)) else _plain(v, secrets, depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [_plain(v, secrets, depth + 1) for v in value]
    return _scrub_text(f"<{type(value).__name__}>", secrets)


def sanitize(value: Any, *, secrets: tuple[str, ...] = (), max_chars: int = MAX_TRACE_CHARS) -> Any:
    """Return a JSON-safe copy of `value`, truncated to roughly `max_chars` characters."""
    try:
        plain = _plain(value, secrets, 0)
        if isinstance(plain, str):
            return _truncate(plain, max_chars)
        encoded = json.dumps(plain, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) <= max_chars:
            return plain
        return _truncate(encoded, max_chars)
    except Exception:
        return "[unserializable]"


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}…[truncated {len(text) - max_chars} chars]"

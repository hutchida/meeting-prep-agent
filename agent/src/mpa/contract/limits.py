"""Size limits. Size is the UTF-8 byte length of compact JSON, same as the TypeScript side."""

from __future__ import annotations

import json
from typing import Any, Final, Literal

from pydantic import BaseModel

LIMITS: Final[dict[str, int]] = {
    "AGENT_EVENT_MAX_BYTES": 8192,
    "BRIEFING_PACK_MAX_BYTES": 40960,
    "TOOL_RESULT_MAX_ITEMS": 10,
    "TOOL_RESULT_ITEM_MAX_BYTES": 4096,
    "EMAIL_MAX_BYTES": 6144,
}

LimitKind = Literal["agent_event", "briefing_pack", "tool_result", "email"]


class LimitError(ValueError):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(f"{kind}: {message}")
        self.kind = kind


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    return value


def json_bytes(value: Any) -> int:
    return len(json.dumps(_plain(value), separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def assert_within_limit(kind: LimitKind, value: Any) -> None:
    """Raise LimitError if `value` is over the size limit for `kind`. Does not validate shape."""
    plain = _plain(value)
    if kind in ("agent_event", "briefing_pack", "email"):
        maximum = LIMITS[
            {
                "agent_event": "AGENT_EVENT_MAX_BYTES",
                "briefing_pack": "BRIEFING_PACK_MAX_BYTES",
                "email": "EMAIL_MAX_BYTES",
            }[kind]
        ]
        size = json_bytes(plain)
        if size > maximum:
            raise LimitError(kind, f"{size} bytes exceeds {maximum}")
        return
    items = plain.get("items") if isinstance(plain, dict) else None
    if not isinstance(items, list):
        raise LimitError(kind, "missing items array")
    if len(items) > LIMITS["TOOL_RESULT_MAX_ITEMS"]:
        raise LimitError(kind, f"{len(items)} items exceeds {LIMITS['TOOL_RESULT_MAX_ITEMS']}")
    for i, item in enumerate(items):
        size = json_bytes(item)
        if size > LIMITS["TOOL_RESULT_ITEM_MAX_BYTES"]:
            raise LimitError(
                kind, f"item {i} is {size} bytes, exceeds {LIMITS['TOOL_RESULT_ITEM_MAX_BYTES']}"
            )

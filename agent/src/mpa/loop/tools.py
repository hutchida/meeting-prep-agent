"""Tool registry and the shaping of tool results for the model and for events."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from mpa.contract import LIMITS, ToolSpec, json_bytes
from mpa.guardrails.injection import InjectionFlag, screen_item
from mpa.loop.events import clip

Handler = Callable[[dict[str, Any]], Awaitable[Any]]
MAX_ITEMS = LIMITS["TOOL_RESULT_MAX_ITEMS"]
MAX_ITEM_BYTES = LIMITS["TOOL_RESULT_ITEM_MAX_BYTES"]
_NOUN = {
    "E": "email",
    "C": "chat message",
    "D": "doc",
    "N": "news item",
    "P": "contact",
    "M": "meeting",
}


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    handler: Handler


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool]) -> None:
        self._tools = {t.spec.name: t for t in tools}

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[ToolSpec]:
        return [self._tools[n].spec for n in sorted(self._tools)]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)


@dataclass
class Shaped:
    """A tool result ready for the model, plus what the loop records about it."""

    text: str
    items: list[dict[str, Any]]
    ids: list[str]
    summary: str
    flags: list[InjectionFlag]


def _dump(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    return [
        v.model_dump(mode="json", exclude_none=True) if isinstance(v, BaseModel) else dict(v)
        for v in values
    ]


def _fit_item(item: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Shorten the longest string field until the item is within the contract size."""
    trimmed = False
    item = dict(item)
    while json_bytes(item) > MAX_ITEM_BYTES:
        key = max((k for k, v in item.items() if isinstance(v, str)), key=lambda k: len(item[k]))
        value = item[key]
        excess = json_bytes(item) - MAX_ITEM_BYTES
        item[key] = value[: max(0, len(value) - max(excess, 16))].rstrip() + "…"
        trimmed = True
    return item, trimmed


def _title(item: dict[str, Any]) -> str:
    return str(item.get("title") or item.get("subject") or item.get("name") or item.get("id", ""))


def shape_result(tool: str, value: Any) -> Shaped:
    """Screen, cap (<= 10 items, <= 4 KB each) and wrap a handler result as untrusted data."""
    dumped = _dump(value)
    total = len(dumped)
    truncated = total > MAX_ITEMS
    items: list[dict[str, Any]] = []
    flags: list[InjectionFlag] = []
    for raw in dumped[:MAX_ITEMS]:
        cleaned, removed = screen_item(raw)
        for span in removed:
            flags.append(
                InjectionFlag(str(raw.get("type", "")), str(raw.get("id", "")), span[:300])
            )
        fitted, trimmed = _fit_item(cleaned)
        truncated = truncated or trimmed
        items.append(fitted)
    ids = [str(i["id"]) for i in items if "id" in i]
    envelope = {"items": items, "total_matches": total, "truncated": truncated}
    body = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False)
    body = body.replace("</untrusted_data", "[/untrusted_data")
    text = f'<untrusted_data tool="{tool}">\n{body}\n</untrusted_data>'
    return Shaped(text, items, ids, _summary(items, ids), flags)


def _summary(items: list[dict[str, Any]], ids: list[str]) -> str:
    if not items:
        return "no results"
    noun = _NOUN.get(ids[0][:1], "item") if ids else "item"
    if len(items) == 1:
        return clip(f"{noun} {ids[0]}: {_title(items[0])}", 300)
    return clip(f"{len(items)} {noun}s: {', '.join(ids)}", 300)


def event_args(arguments: dict[str, Any]) -> dict[str, float | bool | str]:
    """Tool arguments as the event contract allows them: numbers, booleans, short strings."""
    out: dict[str, float | bool | str] = {}
    for key, value in sorted(arguments.items()):
        if isinstance(value, bool | int | float):
            out[str(key)[:64]] = value
        else:
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            out[str(key)[:64]] = clip(text, 200)
    return out

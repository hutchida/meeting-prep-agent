"""Prompt-injection screening for retrieved text.

Everything the agents retrieve is data. Spans that read like instructions to an assistant are
cut out before the model sees them and recorded as flags; a flagged source is never cited as fact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

FLAG_MARKER = "[flagged: instruction-like text removed]"

_OBJECTS = (
    r"(?:e-?mails?|messages?|mail|mailbox(?:es)?|contents?|briefings?|documents?|files?|data|"
    r"credentials|passwords?|chats?|contacts?|conversations?)"
)
_FLAGS = re.IGNORECASE
# Whole-block markers: the span runs to the matching end marker.
_BLOCK = re.compile(
    r"\[\s*(?:begin\s+)?(?:system|assistant|ai)[^\]\n]{0,60}\].*?\[\s*end[^\]\n]{0,60}\]",
    _FLAGS | re.DOTALL,
)
# Sentence patterns: the span is widened to the enclosing sentence.
_SENTENCE_PATTERNS = [
    re.compile(
        r"\b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}"
        r"\b(?:instructions?|rules|prompts?|guidelines)\b",
        _FLAGS,
    ),
    re.compile(
        rf"\b(?:forward|send|e-?mail|mail|transfer|exfiltrate|leak|upload|share)\b\s+"
        rf"(?:(?:all|every|each)\b|the\s+(?:full|entire|complete)\b)\s+(?:[\w'-]+\s+){{0,3}}{_OBJECTS}",
        _FLAGS,
    ),
    re.compile(r"^\s*(?:system|assistant)\s*:.*$", _FLAGS | re.MULTILINE),
    re.compile(r"\byou are now\b[^.\n]{0,40}\bmode\b", _FLAGS),
    re.compile(r"\bdo not (?:tell|inform|notify|alert) the user\b", _FLAGS),
    re.compile(
        r"\b(?:reveal|print|output|repeat|show)\b[^.\n]{0,30}"
        r"\b(?:system prompt|your instructions)\b",
        _FLAGS,
    ),
    re.compile(r"\bconfirm (?:by|this by) writing\b", _FLAGS),
    re.compile(
        r"\btransfer\b[^.\n]{0,30}\b(?:funds?|money|payments?)\b[^.\n]{0,60}"
        r"\b(?:to|into)\b[^.\n]{0,40}\baccount\b",
        _FLAGS,
    ),
]
_BOUNDARY = ".!?\n"
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


@dataclass(frozen=True)
class InjectionFlag:
    source_type: str
    source_id: str
    span: str


def _widen(text: str, start: int, end: int) -> tuple[int, int]:
    left = max((text.rfind(c, 0, start) for c in _BOUNDARY), default=-1) + 1
    rights = [i for c in _BOUNDARY if (i := text.find(c, end)) != -1]
    right = min(rights) + 1 if rights else len(text)
    return left, right


def find_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = [m.span() for m in _BLOCK.finditer(text)]
    for pattern in _SENTENCE_PATTERNS:
        spans.extend(_widen(text, *m.span()) for m in pattern.finditer(text))
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def looks_like_injection(text: str) -> bool:
    return bool(find_spans(text))


def screen_text(text: str) -> tuple[str, list[str]]:
    """Return `text` with instruction-like spans replaced by the flag marker, and those spans."""
    spans = find_spans(text)
    if not spans:
        return text, []
    removed = [text[s:e].strip() for s, e in spans]
    out = text
    for s, e in reversed(spans):
        out = out[:s] + FLAG_MARKER + out[e:]
    return out, removed


def screen_item(item: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Screen every top-level string field of a tool-result item."""
    cleaned: dict[str, Any] = {}
    removed: list[str] = []
    for key, value in item.items():
        if isinstance(value, str) and key not in ("id", "type"):
            cleaned[key], found = screen_text(value)
            removed.extend(found)
        else:
            cleaned[key] = value
    return cleaned, removed


def echoes_span(sentence: str, spans: list[str]) -> bool:
    """True if `sentence` repeats an address or a run of five words from a removed span."""
    words = re.findall(r"\w+", sentence.lower())
    grams = {" ".join(words[i : i + 5]) for i in range(len(words) - 4)}
    for span in spans:
        if any(a.lower() in sentence.lower() for a in _EMAIL_RE.findall(span)):
            return True
        sw = re.findall(r"\w+", span.lower())
        if any(" ".join(sw[i : i + 5]) in grams for i in range(len(sw) - 4)):
            return True
    return False

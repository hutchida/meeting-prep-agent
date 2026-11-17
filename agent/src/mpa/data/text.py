"""Tokenisation and snippet extraction shared by all retrieval indexes."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from functools import lru_cache

STOPWORDS = frozenset(
    "a an and are as at be been by do does for from had has have how i in is it its me my "
    "of on or our so than that the their then there this to was we were what when where which "
    "who whom why will with you your example test".split()
)

_TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)*|[^\W_]+")
SNIPPET_CHARS = 240


def _fold(word: str) -> str:
    decomposed = unicodedata.normalize("NFKD", word)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


@lru_cache(maxsize=1 << 16)
def normalise_token(raw: str) -> str:
    if raw[0].isdigit():
        return raw.replace(",", "")
    return _stem(_fold(raw))


def tokenise(text: str) -> list[str]:
    tokens = (normalise_token(m.group()) for m in _TOKEN_RE.finditer(text))
    return [t for t in tokens if t and t not in STOPWORDS]


def weighted(*fields: tuple[str, int]) -> list[str]:
    """Tokenise `(text, weight)` pairs; a weight of n repeats that field's tokens n times."""
    out: list[str] = []
    for text, weight in fields:
        out.extend(tokenise(text) * weight)
    return out


def shorten(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def make_snippet(text: str, query_terms: Iterable[str], width: int = SNIPPET_CHARS) -> str:
    """Return at most `width` chars of `text` around the densest cluster of query terms."""
    flat = " ".join(text.split())
    if len(flat) <= width:
        return flat
    terms = set(query_terms)
    hits = [m.start() for m in _TOKEN_RE.finditer(flat) if normalise_token(m.group()) in terms]
    if not hits:
        return flat[: width - 1].rstrip() + "…"
    budget = width - 2
    best_start, best_count = hits[0], 0
    for h in hits:
        count = sum(1 for other in hits if h <= other < h + budget - 40)
        if count > best_count:
            best_start, best_count = h, count
    start = max(0, best_start - 40)
    if start > 0:
        space = flat.find(" ", start)
        start = space + 1 if 0 <= space < best_start else start
    end = min(len(flat), start + budget)
    if end < len(flat):
        space = flat.rfind(" ", start, end)
        end = space if space > start else end
    body = flat[start:end].strip()
    return ("…" if start > 0 else "") + body + ("…" if end < len(flat) else "")

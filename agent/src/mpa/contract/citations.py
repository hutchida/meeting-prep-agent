"""Inline citation helpers. Behaviour must match packages/contract/src/citations.ts
(parity is tested against packages/contract/fixtures/citation_cases.json)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

ID_PREFIX: dict[str, str] = {
    "email": "E",
    "chat": "C",
    "doc": "D",
    "news": "N",
    "contact": "P",
    "cal": "M",
}

CITATION_TOKEN_PATTERN = (
    r"\[(?:email:E[0-9]{1,9}|chat:C[0-9]{1,9}|doc:D[0-9]{1,9}"
    r"|news:N[0-9]{1,9}|contact:P[0-9]{1,9}|cal:M[0-9]{1,9})\]"
)
_TOKEN_RE = re.compile(CITATION_TOKEN_PATTERN)
_ID_RE = re.compile(r"[0-9]{1,9}")


@dataclass(frozen=True)
class CitationRef:
    type: str
    id: str

    def as_dict(self) -> dict[str, str]:
        return {"type": self.type, "id": self.id}


def citation_token(citation: CitationRef | Mapping[str, str]) -> str:
    """Render `[type:id]`; raises ValueError if the id prefix does not fit the type."""
    ctype, cid = (
        (citation.type, citation.id)
        if isinstance(citation, CitationRef)
        else (citation.get("type", ""), citation.get("id", ""))
    )
    prefix = ID_PREFIX.get(ctype)
    if prefix is None or not cid.startswith(prefix) or not _ID_RE.fullmatch(cid[1:]):
        raise ValueError(f"invalid citation: {ctype}:{cid}")
    return f"[{ctype}:{cid}]"


def parse_citations(text: str) -> list[CitationRef]:
    """All valid inline citation tokens in `text`, in order (duplicates kept)."""
    out: list[CitationRef] = []
    for match in _TOKEN_RE.finditer(text):
        ctype, cid = match.group(0)[1:-1].split(":")
        out.append(CitationRef(ctype, cid))
    return out

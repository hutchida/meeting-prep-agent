"""Cite-or-drop verifier.

For every sentence: each cited id must exist (DataSource.get_source) and the cited sources
must support the sentence (deterministic check in `support.py`). Anything else is removed and
counted. Notes (kind="note") carry no factual claim and are exempt; they are only ever created by
the pipeline itself, never from model output.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from mpa.contract import DataSource, DataSourceError, SourceItem, citation_token
from mpa.contract.assemble import SECTION_IDS, SECTION_TITLES
from mpa.contract.models import DroppedSentence, FactSentence, NoteSentence
from mpa.guardrails.injection import echoes_span, looks_like_injection
from mpa.guardrails.support import shares_content, support
from mpa.loop.events import clip

Key = tuple[str, str]
MAX_REPORTED_DROPS = 10


@dataclass(frozen=True)
class RawSentence:
    text: str
    citations: tuple[Key, ...] = ()
    kind: str = "fact"


@dataclass
class RawSection:
    id: str
    sentences: list[RawSentence] = field(default_factory=list)

    @property
    def title(self) -> str:
        return SECTION_TITLES[self.id]


@dataclass
class VerifiedSection:
    id: str
    title: str
    sentences: list[FactSentence | NoteSentence]


@dataclass
class VerifierReport:
    sections: list[VerifiedSection]
    total: int
    kept: int
    dropped: list[DroppedSentence]

    @property
    def dropped_count(self) -> int:
        return self.total - self.kept

    def dropped_in(self, section_id: str) -> int:
        return sum(1 for d in self.dropped if d.section_id == section_id)


def source_text(item: SourceItem) -> str:
    """All human-readable text of a source item (what a citation can be checked against)."""
    root: Any = item.root
    parts: list[Any]
    match root.type:
        case "email":
            parts = [root.subject, root.sender, *root.to, *root.cc, root.date, root.body]
        case "chat":
            parts = [root.channel, root.author, root.ts, root.text]
        case "doc":
            parts = [root.title, root.kind, root.author, root.date, root.body]
        case "news":
            parts = [root.title, root.source, root.published, root.about or "", root.body]
        case "contact":
            parts = [root.name, root.email, root.organization, root.role, root.notes]
        case _:
            parts = [root.title, root.start, root.end, root.location, root.description]
    return "\n".join(str(p) for p in parts)


class Verifier:
    def __init__(
        self,
        data: DataSource,
        *,
        flagged: dict[Key, list[str]] | None = None,
        allowed: Iterable[Key] | None = None,
        concurrency: int = 8,
    ) -> None:
        self._data = data
        self._flagged = flagged or {}
        self._spans = [s for spans in self._flagged.values() for s in spans]
        self._allowed = set(allowed) if allowed is not None else None
        self._sem = asyncio.Semaphore(concurrency)
        self._texts: dict[Key, str | None] = {}

    async def _fetch(self, key: Key) -> None:
        if key in self._texts:
            return
        async with self._sem:
            for attempt in (1, 2):
                try:
                    item = await self._data.get_source(key[0], key[1])  # type: ignore[arg-type]
                    self._texts[key] = source_text(item)
                    return
                except KeyError:
                    break
                except DataSourceError:
                    if attempt == 2:
                        break
                    await asyncio.sleep(0.05)
                except Exception:
                    break
            self._texts[key] = None

    async def verify(self, sections: list[RawSection]) -> VerifierReport:
        keys = {
            c
            for s in sections
            for sent in s.sentences
            if sent.kind == "fact"
            for c in sent.citations
            if (self._allowed is None or c in self._allowed) and c not in self._flagged
        }
        await asyncio.gather(*(self._fetch(k) for k in sorted(keys)))
        by_id = {s.id: s for s in sections}
        out: list[VerifiedSection] = []
        total = kept = 0
        dropped: list[DroppedSentence] = []
        for sid in SECTION_IDS:
            section = by_id.get(sid) or RawSection(sid)
            verified: list[FactSentence | NoteSentence] = []
            for sent in section.sentences:
                total += 1
                if sent.kind == "note":
                    verified.append(NoteSentence.model_validate(self._note(sent)))
                    kept += 1
                    continue
                reason, cites = self._check(sent)
                if reason is None:
                    verified.append(FactSentence.model_validate(self._fact(sent, cites)))
                    kept += 1
                else:
                    dropped.append(
                        DroppedSentence(section_id=sid, reason=reason, text=clip(sent.text, 200))  # type: ignore[arg-type]
                    )
            out.append(VerifiedSection(sid, SECTION_TITLES[sid], verified))
        return VerifierReport(out, total, kept, dropped)

    def _check(self, sent: RawSentence) -> tuple[str | None, tuple[Key, ...]]:
        if (
            looks_like_injection(sent.text)
            or echoes_span(sent.text, self._spans)
            or any(c in self._flagged for c in sent.citations)
        ):
            return "injection", ()
        if not sent.citations:
            return "no_citation", ()
        for c in sent.citations:
            if self._allowed is not None and c not in self._allowed:
                return "invalid_citation", ()
            if self._texts.get(c) is None:
                return "invalid_citation", ()
        combined = "\n".join(self._texts[c] or "" for c in sent.citations)
        if not support(sent.text, combined).supported:
            return "unsupported", ()
        useful = tuple(
            c for c in sent.citations if shares_content(sent.text, self._texts[c] or "") >= 2
        )
        return None, useful or sent.citations

    @staticmethod
    def _fact(sent: RawSentence, cites: tuple[Key, ...]) -> dict[str, Any]:
        seen: list[Key] = []
        for c in cites:
            if c not in seen:
                seen.append(c)
        return {
            "text": sent.text,
            "citations": [{"type": t, "id": i} for t, i in seen[:8]],
        }

    @staticmethod
    def _note(sent: RawSentence) -> dict[str, Any]:
        return {
            "text": sent.text,
            "citations": [{"type": t, "id": i} for t, i in sent.citations[:8]],
            "kind": "note",
        }


def tokens_for(keys: Iterable[Key]) -> list[str]:
    return [citation_token({"type": t, "id": i}) for t, i in keys]

"""LLM judge: fact recall and trap check (one call) and hallucination check (one or two calls).

Prompts live in evals/prompts/*.md. Every call goes through LLMClient at temperature 0, replies are
strict JSON validated by Pydantic, and an invalid reply is retried once with the validation error.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from mpa.contract import BriefingPack, LLMClient, LLMMessage
from mpa.evals.gold import PROMPTS_DIR
from mpa.evals.models import ClaimsJudgement, FactsJudgement, GoldFacts

T = TypeVar("T", bound=BaseModel)

MAX_SOURCE_CHARS = 2500
CLAIM_CHUNK = 40
MAX_CLAIM_CHUNKS = 2


class JudgeError(Exception):
    """The judge could not return a valid verdict after one retry."""


@dataclass(frozen=True)
class NumberedSentence:
    index: int
    section_id: str
    text: str
    note: bool
    citations: tuple[str, ...]


def numbered_sentences(pack: BriefingPack) -> list[NumberedSentence]:
    out: list[NumberedSentence] = []
    for section in pack.sections:
        for sentence in section.sentences:
            root: Any = getattr(sentence, "root", sentence)
            out.append(
                NumberedSentence(
                    index=len(out) + 1,
                    section_id=section.id,
                    text=root.text,
                    note=getattr(root, "kind", None) == "note",
                    citations=tuple(
                        f"{getattr(c, 'root', c).type}:{getattr(c, 'root', c).id}"
                        for c in root.citations
                    ),
                )
            )
    return out


def render_source(item: Any) -> str:
    """Plain text of a SourceItem (or its raw dict) for the hallucination judge."""
    data: dict[str, Any] = (
        item
        if isinstance(item, dict)
        else getattr(item, "root", item).model_dump(mode="json", exclude_none=True)
    )
    kind = data.get("type")
    if kind == "email":
        text = (
            f"Email from {data.get('sender')} on {data.get('date')}. "
            f"Subject: {data.get('subject')}\n{data.get('body')}"
        )
    elif kind == "chat":
        text = (
            f"Chat by {data.get('author')} in {data.get('channel')} at {data.get('ts')}: "
            f"{data.get('text')}"
        )
    elif kind == "doc":
        text = (
            f"Document '{data.get('title')}' by {data.get('author')} ({data.get('date')})\n"
            f"{data.get('body')}"
        )
    elif kind == "news":
        text = (
            f"News '{data.get('title')}' ({data.get('source')}, {data.get('published')}), "
            f"about: {data.get('about', 'n/a')}\n{data.get('body')}"
        )
    elif kind == "contact":
        text = (
            f"Contact {data.get('name')}, {data.get('role')} at {data.get('organization')}. "
            f"{data.get('notes', '')}"
        )
    elif kind == "cal":
        text = (
            f"Calendar event '{data.get('title')}' {data.get('start')} to {data.get('end')}, "
            f"attendees {', '.join(data.get('attendees', []))}. {data.get('description', '')}"
        )
    else:
        text = json.dumps(data, sort_keys=True)
    return text[:MAX_SOURCE_CHARS]


def _extract_json(text: str) -> Any:
    stripped = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.S)
    if fenced:
        stripped = fenced.group(1)
    if not stripped.startswith("{"):
        start, end = stripped.find("{"), stripped.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("reply contains no JSON object")
        stripped = stripped[start : end + 1]
    return json.loads(stripped)


@dataclass
class Judge:
    llm: LLMClient
    prompts_dir: Path = PROMPTS_DIR
    max_tokens: int = 4000
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    models: set[str] = field(default_factory=set)

    def _prompt(self, name: str) -> str:
        return (self.prompts_dir / f"{name}.md").read_text("utf-8")

    async def _ask(self, system: str, user: str, model: type[T], tag: str, check: Any) -> T:
        messages = [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user),
        ]
        last_error = ""
        for attempt in range(2):
            response = await self.llm.chat(
                messages, temperature=0.0, max_tokens=self.max_tokens, tag=tag
            )
            self.calls += 1
            self.tokens_in += response.usage.prompt_tokens
            self.tokens_out += response.usage.completion_tokens
            self.cost_usd += response.usage.cost_usd
            self.models.add(response.model)
            reply = response.message.content or ""
            try:
                parsed = model.model_validate(_extract_json(reply))
                check(parsed)
                return parsed
            except (ValueError, ValidationError) as err:
                last_error = str(err).splitlines()[0][:300] if str(err) else type(err).__name__
                if attempt == 0:
                    messages = [
                        *messages,
                        LLMMessage(role="assistant", content=reply),
                        LLMMessage(
                            role="user",
                            content=f"Your reply was invalid: {last_error}. "
                            "Return only the corrected JSON object.",
                        ),
                    ]
        raise JudgeError(f"{tag}: invalid reply after retry: {last_error}")

    async def judge_facts(self, pack: BriefingPack, gold: GoldFacts) -> FactsJudgement:
        sentences = numbered_sentences(pack)
        briefing = "\n".join(f"[{s.index}] ({s.section_id}) {s.text}" for s in sentences)
        facts = "\n".join(
            f"- {f.id}: {f.statement}" for f in sorted(gold.key_facts, key=lambda f: f.id)
        )
        traps = "\n".join(
            f"- {t.id} ({t.kind}): {t.description} RULE: {t.rule}"
            for t in sorted(gold.traps, key=lambda t: t.id)
        )
        user = (
            f"<BRIEFING>\n{briefing}\n</BRIEFING>\n\n<KEY_FACTS>\n{facts}\n</KEY_FACTS>\n\n"
            f"<TRAPS>\n{traps}\n</TRAPS>"
        )
        fact_ids = sorted(f.id for f in gold.key_facts)
        trap_ids = sorted(t.id for t in gold.traps)
        n = len(sentences)

        def check(j: FactsJudgement) -> None:
            if sorted(v.id for v in j.facts) != fact_ids:
                raise ValueError(f"facts must list exactly these ids once: {', '.join(fact_ids)}")
            if sorted(v.id for v in j.traps) != trap_ids:
                raise ValueError(f"traps must list exactly these ids once: {', '.join(trap_ids)}")
            for fv in j.facts:
                _check_indexes(fv.id, fv.sentence_indexes, n, need=fv.verdict != "no")
            for tv in j.traps:
                _check_indexes(tv.id, tv.sentence_indexes, n, need=tv.violated)

        parsed = await self._ask(
            self._prompt("judge_facts"), user, FactsJudgement, "judge:facts", check
        )
        order = {f.id: i for i, f in enumerate(gold.key_facts)}
        t_order = {t.id: i for i, t in enumerate(gold.traps)}
        return FactsJudgement(
            facts=sorted(parsed.facts, key=lambda v: order[v.id]),
            traps=sorted(parsed.traps, key=lambda v: t_order[v.id]),
        )

    async def judge_claims(
        self, pack: BriefingPack, sources: dict[str, str]
    ) -> list[tuple[NumberedSentence, str]]:
        """Unsupported fact sentences with the judge's reason, in sentence order."""
        claims = [s for s in numbered_sentences(pack) if not s.note]
        if not claims:
            return []
        size = max(CLAIM_CHUNK, math.ceil(len(claims) / MAX_CLAIM_CHUNKS))
        found: dict[int, str] = {}
        for start in range(0, len(claims), size):
            chunk = claims[start : start + size]
            cited = sorted({c for s in chunk for c in s.citations})
            source_block = "\n".join(
                f"[{c}] {sources.get(c, '(source unavailable)')}" for c in cited
            )
            claim_block = "\n".join(
                f"[{s.index}] {s.text} (cites: {', '.join(s.citations) or 'none'})" for s in chunk
            )
            user = f"<SOURCES>\n{source_block}\n</SOURCES>\n\n<CLAIMS>\n{claim_block}\n</CLAIMS>"
            allowed = {s.index for s in chunk}

            def check(j: ClaimsJudgement, allowed: set[int] = allowed) -> None:
                seen: set[int] = set()
                for u in j.unsupported:
                    if u.sentence_index not in allowed:
                        raise ValueError(f"sentence_index {u.sentence_index} is not in CLAIMS")
                    if u.sentence_index in seen:
                        raise ValueError(f"sentence_index {u.sentence_index} listed twice")
                    seen.add(u.sentence_index)

            parsed = await self._ask(
                self._prompt("judge_claims"), user, ClaimsJudgement, f"judge:claims{start}", check
            )
            for u in parsed.unsupported:
                found[u.sentence_index] = u.reason
        by_index = {s.index: s for s in claims}
        return [(by_index[i], found[i]) for i in sorted(found)]


def _check_indexes(item_id: str, indexes: list[int], n: int, *, need: bool) -> None:
    if need and not indexes:
        raise ValueError(f"{item_id}: sentence_indexes must not be empty here")
    for i in indexes:
        if not 1 <= i <= n:
            raise ValueError(f"{item_id}: sentence index {i} is outside 1..{n}")

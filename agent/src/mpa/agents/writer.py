"""The Writer: one LLM call that turns findings into the seven sections, plus a no-LLM fallback."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from mpa.agents.context import AGENT_NAMES, MeetingContext
from mpa.agents.prompts import WRITER_SYSTEM, writer_user
from mpa.contract import LLMClient, LLMMessage, Span, Tracer
from mpa.contract.assemble import SECTION_IDS
from mpa.contract.citations import CITATION_TOKEN_PATTERN
from mpa.contract.models import FactSentence
from mpa.guardrails.support import content_tokens
from mpa.guardrails.verifier import Key, RawSection, RawSentence
from mpa.llm.errors import LLMError
from mpa.loop.budget import Budget, BudgetExceeded, Emit, report_budget_hit
from mpa.loop.events import clip

WRITER_MAX_TOKENS = 4000
MAX_SENTENCES = 12
_PREFIX = {"E": "email", "C": "chat", "D": "doc", "N": "news", "P": "contact", "M": "cal"}
_REF = re.compile(r"^(?:(email|chat|doc|news|contact|cal)\s*:\s*)?([ECDNPM]\d{1,9})$")
_TOKEN = re.compile(CITATION_TOKEN_PATTERN)
_OPEN = re.compile(
    r"\b(promis\w*|due|deadline|outstanding|still|not (?:yet|been)|waiting|asked|request\w*|owes?|"
    r"pending|chase\w*|must|needs?|before|by \d)\b",
    re.I,
)
_CONFLICT = re.compile(
    r"\b(but|whereas|however|versus|vs\.?|instead|conflict\w*|inconsisten\w*|differs?|disagree\w*)\b",
    re.I,
)


_MONTHS = (
    "january february march april may june july august september october november december "
    "jan feb mar apr jun jul aug sep sept oct nov dec monday tuesday wednesday thursday friday "
    "saturday sunday"
).split()
_DATE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({'|'.join(_MONTHS)})\b(?:,?\s+(\d{{4}}))?"
    rf"|\b({'|'.join(_MONTHS)})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?",
    re.I,
)
_FIGURE = re.compile(
    r"(?<![\w.])(?:(?P<cur>[£$€])\s?(?P<a>\d[\d,]*(?:\.\d+)?)\s?(?P<k>k|m|bn)?\b"
    r"|(?P<b>\d[\d,]*(?:\.\d+)?)\s?(?P<unit>%|[A-Za-z]+))",
    re.I,
)
MAX_HINTS = 6
HINT_MIN_SHARED = 2


@dataclass(frozen=True)
class Finding:
    agent: str
    text: str
    citations: tuple[Key, ...]


@dataclass
class WriterResult:
    sections: list[RawSection]
    mode: Literal["llm", "fallback"]
    reason: str | None = None


class WriterFormatError(ValueError):
    pass


def meeting_findings(ctx: MeetingContext) -> list[Finding]:
    m = ctx.meeting
    cite = (("cal", m.id),)
    out = [Finding("calendar", f"{m.title}: {ctx.when}, {m.location}.", cite)]
    if m.description.strip():
        out.append(Finding("calendar", f"Purpose of the meeting: {m.description.strip()}", cite))
    return out


def _figures(text: str) -> tuple[dict[str, set[str]], str]:
    """Figures grouped by kind (currency, unit word or date), and the text without them."""
    out: dict[str, set[str]] = {}

    def date(m: re.Match[str]) -> str:
        day, month = (m[1], m[2]) if m[1] else (m[5], m[4])
        out.setdefault("date", set()).add(f"{int(day)} {month.lower()[:3]}")
        return " "

    text = _DATE.sub(date, text)

    def figure(m: re.Match[str]) -> str:
        if m["cur"]:
            value = m["a"].replace(",", "") + (m["k"] or "").lower()
            out.setdefault(m["cur"], set()).add(value)
        else:
            unit = m["unit"].lower().rstrip("s") if m["unit"] != "%" else "%"
            if unit in ("st", "nd", "rd", "th", "x", "q", "h"):
                return " "
            out.setdefault(unit, set()).add(m["b"].replace(",", ""))
        return " "

    return out, _FIGURE.sub(figure, text)


def _cites(f: Finding) -> str:
    return ", ".join(f"{t}:{i}" for t, i in f.citations)


def conflict_hints(findings: list[Finding]) -> list[str]:
    """Pairs of findings on the same subject that give different figures of the same kind."""
    info = []
    for f in findings:
        if f.agent == "calendar":
            continue
        figs, rest = _figures(f.text)
        info.append((f, figs, content_tokens(rest)))
    hints: list[tuple[int, str]] = []
    for i, (a, figs_a, words_a) in enumerate(info):
        for b, figs_b, words_b in info[i + 1 :]:
            if set(a.citations) == set(b.citations) or not (words_a and words_b):
                continue
            shared = len(words_a & words_b)
            if shared < HINT_MIN_SHARED or shared < 0.25 * min(len(words_a), len(words_b)):
                continue
            for kind in sorted(figs_a.keys() & figs_b.keys()):
                if figs_a[kind] == figs_b[kind]:
                    continue
                if kind == "date" and shared < 2 * HINT_MIN_SHARED:
                    continue
                hints.append(
                    (
                        shared,
                        f'- "{clip(a.text, 130)}" ({_cites(a)}) vs "{clip(b.text, 130)}" '
                        f"({_cites(b)}): different {kind} values",
                    )
                )
                break
    hints.sort(key=lambda h: -h[0])
    return [h for _, h in hints[:MAX_HINTS]]


def finding_line(f: Finding) -> str:
    return f"[{f.agent}] {f.text} | cites: {_cites(f)}"


def collect_findings(
    ctx: MeetingContext, reports: dict[str, Any], flagged: set[Key]
) -> list[Finding]:
    """Calendar facts first, then each agent's findings in a fixed agent order."""
    out = meeting_findings(ctx)
    for agent in AGENT_NAMES:
        report = reports.get(agent)
        if report is None or report.status != "done":
            continue
        for f in report.findings:
            if not isinstance(f, FactSentence):
                continue
            cites = tuple((c.type, c.id) for c in f.citations)
            if any(c in flagged for c in cites):
                continue
            out.append(Finding(agent, f.text, cites))
    return out


def parse_writer_json(raw: str) -> list[RawSection]:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise WriterFormatError("no JSON object found")
    try:
        data = json.loads(raw[start : end + 1])
    except ValueError as err:
        raise WriterFormatError(f"invalid JSON: {err}") from None
    sections = data.get("sections") if isinstance(data, dict) else None
    if not isinstance(sections, list):
        raise WriterFormatError('top-level "sections" array is missing')
    by_id: dict[str, RawSection] = {}
    for s in sections:
        if not isinstance(s, dict) or s.get("id") not in SECTION_IDS:
            raise WriterFormatError(
                f"unknown section id {s.get('id') if isinstance(s, dict) else s!r}"
            )
        if s["id"] in by_id:
            raise WriterFormatError(f"section {s['id']} appears twice")
        sentences = s.get("sentences")
        if not isinstance(sentences, list):
            raise WriterFormatError(f"section {s['id']} needs a sentences array")
        parsed: list[RawSentence] = []
        for sent in sentences[:MAX_SENTENCES]:
            if not isinstance(sent, dict) or not isinstance(sent.get("text"), str):
                raise WriterFormatError(
                    f"section {s['id']}: each sentence needs text and citations"
                )
            text = sent["text"]
            cites: list[Key] = [
                (m[1:-1].split(":")[0], m[1:-1].split(":")[1]) for m in _TOKEN.findall(text)
            ]
            text = clip(_TOKEN.sub("", text), 600)
            refs = sent.get("citations", [])
            if not isinstance(refs, list):
                raise WriterFormatError(f"section {s['id']}: citations must be an array")
            for ref in refs:
                m = _REF.match(str(ref).strip())
                if m is None or (m.group(1) and _PREFIX[m.group(2)[0]] != m.group(1)):
                    raise WriterFormatError(
                        f'bad citation {str(ref)[:30]!r}; use "type:ID" like "email:E51"'
                    )
                cites.append((m.group(1) or _PREFIX[m.group(2)[0]], m.group(2)))
            if text.strip():
                parsed.append(RawSentence(text.strip(), tuple(dict.fromkeys(cites))[:8]))
        by_id[s["id"]] = RawSection(s["id"], parsed)
    missing = [i for i in SECTION_IDS if i not in by_id]
    if missing:
        raise WriterFormatError(f"missing sections: {', '.join(missing)}")
    return [by_id[i] for i in SECTION_IDS]


def with_meeting_line(sections: list[RawSection], findings: list[Finding]) -> list[RawSection]:
    """Put the calendar sentence (built from the calendar item itself) first in the glance."""
    line = next((f for f in findings if f.agent == "calendar"), None)
    if line is None:
        return sections
    first = RawSentence(line.text, line.citations)
    return [
        RawSection(s.id, [first, *(x for x in s.sentences if x.text != first.text)])
        if s.id == "meeting_at_a_glance"
        else s
        for s in sections
    ]


def fallback_sections(findings: list[Finding]) -> list[RawSection]:
    """Render findings into sections without a model: grouped by agent, split by simple cues."""

    def sentences(items: list[Finding], limit: int) -> list[RawSentence]:
        return [RawSentence(f.text, f.citations) for f in items[:limit]]

    by_agent = {a: [f for f in findings if f.agent == a] for a in ("calendar", *AGENT_NAMES)}
    corr = by_agent["correspondence"]
    open_items = [f for f in corr if _OPEN.search(f.text)]
    left_off = [f for f in corr if f not in open_items] or corr[:3]
    talking = [f for f in findings if f.agent != "calendar" and _CONFLICT.search(f.text)]
    content = {
        "meeting_at_a_glance": sentences(by_agent["calendar"], 3),
        "client_snapshot": sentences(by_agent["documents"], 6),
        "recent_news": sentences(by_agent["news"], 5),
        "where_we_left_off": sentences(left_off, 6),
        "open_items": sentences(open_items, 6),
        "attendees": sentences(by_agent["attendees"], 8),
        "talking_points_and_risks": sentences(talking, 5),
    }
    return [RawSection(i, content[i]) for i in SECTION_IDS]


async def write_briefing(
    *,
    ctx: MeetingContext,
    findings: list[Finding],
    unavailable: list[str],
    llm: LLMClient,
    budget: Budget,
    tracer: Tracer,
    span: Span,
    emit: Emit,
) -> WriterResult:
    if not any(f.agent != "calendar" for f in findings):
        return WriterResult(fallback_sections(findings), "fallback", "no findings to write from")
    messages = [
        LLMMessage(role="system", content=WRITER_SYSTEM),
        LLMMessage(
            role="user",
            content=writer_user(
                ctx, [finding_line(f) for f in findings], unavailable, conflict_hints(findings)
            ),
        ),
    ]
    error = ""
    for attempt in (1, 2):
        try:
            budget.begin_step("writer")
        except BudgetExceeded as hit:
            report_budget_hit(budget, hit, emit)
            return WriterResult(
                fallback_sections(findings), "fallback", f"{hit.kind} budget reached"
            )
        try:
            response = await llm.chat(
                messages,
                temperature=0.0,
                max_tokens=WRITER_MAX_TOKENS,
                tag="writer" if attempt == 1 else "writer:retry",
            )
        except LLMError as err:
            return WriterResult(fallback_sections(findings), "fallback", clip(str(err), 200))
        budget.charge(response.usage)
        tracer.record_llm(
            span,
            model=response.model,
            input=[m.model_dump(mode="json", exclude_none=True) for m in messages],
            output=response.message.model_dump(mode="json", exclude_none=True),
            usage=response.usage,
            latency_ms=response.latency_ms,
        )
        raw = response.message.content or ""
        try:
            return WriterResult(parse_writer_json(raw), "llm")
        except WriterFormatError as err:
            error = str(err)
            messages = [
                *messages,
                LLMMessage(role="assistant", content=raw),
                LLMMessage(
                    role="user",
                    content=f"That JSON was rejected: {error}. Return the corrected JSON only.",
                ),
            ]
    return WriterResult(fallback_sections(findings), "fallback", f"writer output invalid: {error}")

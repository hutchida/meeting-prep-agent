"""The four sub-agents: each is a prompt, a read-only tool set and one run of the agent loop."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Literal, cast

from mpa.agents.context import AGENT_NAMES, GAP_SOURCE, MeetingContext
from mpa.agents.prompts import goal, system_prompt, user_task
from mpa.agents.tools import build_registry
from mpa.contract import RunDeps, Span
from mpa.contract.models import FactSentence, Gap, NoteSentence
from mpa.guardrails.injection import InjectionFlag
from mpa.guardrails.verifier import RawSentence, Verifier
from mpa.loop import Budget, run_agent_loop
from mpa.loop.budget import Emit
from mpa.loop.events import clip
from mpa.loop.runner import LoopResult, SeenItem

__all__ = ["AGENT_NAMES", "AgentReport", "run_subagent"]

Reason = Literal["timeout", "fault_injected", "budget", "error"]
MAX_SALVAGE = 6
MAX_BACKFILL = 4
_NO_DATA = re.compile(
    r"not found|no (?:such |matching )?(?:record|data|result|match|item|contact|entry)|no data"
    r"|does(?:n't| not) exist|could not be found|couldn't be found|nothing found",
    re.I,
)
_OUTAGE = re.compile(
    r"unavailable|unreachable|not reach|could not (?:reach|connect)|timed? ?out|timeout|"
    r"connection|failed|fault|5\d\d",
    re.I,
)


@dataclass
class AgentReport:
    agent: str
    status: Literal["done", "failed"]
    findings: list[FactSentence | NoteSentence] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    reason: Reason | None = None
    error: str | None = None
    flags: list[InjectionFlag] = field(default_factory=list)
    budget_cut: bool = False


def is_no_data_gap(gap: Gap) -> bool:
    """A missing item is "no data", not a failure: only outages stay as gaps."""
    return bool(_NO_DATA.search(gap.detail)) and not _OUTAGE.search(gap.detail)


def _salvage(seen: dict[tuple[str, str], SeenItem]) -> list[FactSentence | NoteSentence]:
    """Findings taken straight from retrieved items, for an agent the budget stopped early."""
    ordered = sorted(
        seen.values(), key=lambda s: (s.type, int(s.id[1:]) if s.id[1:].isdigit() else 0)
    )
    out: list[FactSentence | NoteSentence] = []
    for item in ordered:
        if item.type not in ("email", "chat", "doc", "news") or not (item.text or item.title):
            continue
        if item.type == "doc" and item.title:
            text = clip(f"Document: {item.title}", 300)
        else:
            text = clip(f"{item.title}: {item.text}" if item.title else item.text, 300)
        out.append(
            FactSentence.model_validate(
                {"text": text, "citations": [{"type": item.type, "id": item.id}]}
            )
        )
        if len(out) >= MAX_SALVAGE:
            break
    return out


async def _backfill_chat(
    findings: list[FactSentence | NoteSentence],
    seen: dict[tuple[str, str], SeenItem],
    ctx: MeetingContext,
    deps: RunDeps,
) -> list[FactSentence | NoteSentence]:
    """Add the client's chat messages that state a date or figure but that no finding cites.

    Chat is informal and often holds the newest value ("engineering says 28 April"). A small
    model sometimes reads such a message and leaves it out, or paraphrases it with a date the
    message does not give, and the support check rightly drops that finding. The Writer needs the
    message to notice when chat disagrees with a document, so it is carried over near-verbatim,
    with the author and date from the chat record.
    """
    from mpa.agents.writer import _figures

    cited = {(c.type, c.id) for f in findings if isinstance(f, FactSentence) for c in f.citations}
    client_word = ctx.client.split()[0].lower() if ctx.client.split() else ""
    extra: list[FactSentence | NoteSentence] = []
    for item in sorted(seen.values(), key=lambda s: (len(s.id), s.id)):
        if item.type != "chat" or (item.type, item.id) in cited or not _figures(item.text)[0]:
            continue
        try:
            msg = await deps.data.get_chat(item.id)
        except Exception:
            continue
        if client_word not in msg.channel.lower() or not _figures(msg.text)[0]:
            continue
        text = clip(f"{msg.author} wrote in {msg.channel} on {msg.ts[:10]}: {msg.text}", 400)
        extra.append(
            FactSentence.model_validate(
                {"text": text, "citations": [{"type": "chat", "id": item.id}]}
            )
        )
        if len(extra) >= MAX_BACKFILL:
            break
    return findings + extra


def _ground(
    result: LoopResult, extra: set[tuple[str, str]]
) -> tuple[list[FactSentence | NoteSentence], int]:
    """Keep findings whose citations were all retrieved (or given in the task) and unflagged."""
    allowed = set(result.seen) | extra
    flagged = {(f.source_type, f.source_id) for f in result.flags}
    kept: list[FactSentence | NoteSentence] = []
    dropped = 0
    assert result.output is not None
    for f in result.output.findings:
        cites = [(c.type, c.id) for c in f.citations]
        if isinstance(f, FactSentence):
            if any(c in flagged for c in cites):
                continue
            if any(c not in allowed for c in cites):
                dropped += 1
                continue
        kept.append(f)
    return kept, dropped


async def _drop_unsupported(
    findings: list[FactSentence | NoteSentence], deps: RunDeps
) -> list[FactSentence | NoteSentence]:
    """Remove findings whose cited sources clearly do not say what the finding says."""
    facts = [f for f in findings if isinstance(f, FactSentence)]
    raw = [RawSentence(f.text, tuple((c.type, c.id) for c in f.citations)) for f in facts]
    try:
        bad = await Verifier(deps.data).unsupported(raw)
    except Exception:
        return findings
    dropped = {id(f) for f, b in zip(facts, bad, strict=True) if b}
    return [f for f in findings if id(f) not in dropped]


async def run_subagent(
    agent: str,
    ctx: MeetingContext,
    deps: RunDeps,
    budget: Budget,
    emit: Emit,
    root: Span,
) -> AgentReport:
    """Run one agent to a terminal event (`subagent_done` or `subagent_failed`)."""
    loop = asyncio.get_running_loop()
    started = loop.time()
    emit("subagent_started", agent=agent, goal=clip(goal(agent, ctx), 300))
    span = deps.tracer.start_span(root, agent, kind="agent", input={"goal": goal(agent, ctx)})

    def finish_failed(reason: Reason, error: str, flags: list[InjectionFlag]) -> AgentReport:
        emit("subagent_failed", agent=agent, reason=reason, error=clip(error, 300))
        span.end(error=clip(error, 200))
        return AgentReport(agent, "failed", reason=reason, error=error, flags=flags)

    try:
        async with asyncio.timeout(deps.settings.subagent_timeout_s):
            result = await run_agent_loop(
                agent=agent,
                llm=deps.llm,
                system_prompt=system_prompt(agent, ctx),
                user_task=user_task(agent, ctx),
                registry=build_registry(agent, deps.data),
                budget=budget,
                emit=emit,
                tracer=deps.tracer,
                span=span,
                gap_source=cast(Literal["email", "docs", "news", "contacts"], GAP_SOURCE[agent]),
            )
    except TimeoutError:
        return finish_failed(
            "timeout", f"{agent} did not finish within {deps.settings.subagent_timeout_s:g} s", []
        )
    except Exception as exc:  # a bug in one agent must not stop the others
        return finish_failed("error", f"unexpected {type(exc).__name__} in {agent}", [])

    duration_ms = round((loop.time() - started) * 1000)
    if result.status == "failed":
        return finish_failed(result.reason or "error", result.error or "agent failed", result.flags)

    gap_source = cast(Literal["email", "docs", "news", "contacts"], GAP_SOURCE[agent])
    extra = {("cal", ctx.meeting.id), *(("contact", p.id) for p in ctx.people)}
    if result.status == "budget":
        findings: list[FactSentence | NoteSentence] = _salvage(result.seen)
        if not findings:
            return finish_failed("budget", result.error or "budget reached", result.flags)
        gaps = [
            Gap(
                source=gap_source,
                reason="budget",
                detail=clip(result.error or "budget reached", 300),
            )
        ]
    else:
        findings, dropped = _ground(result, extra)
        findings = await _drop_unsupported(findings, deps)
        if agent == "correspondence":
            findings = await _backfill_chat(findings, result.seen, ctx, deps)
        assert result.output is not None
        gaps = [g for g in result.output.gaps if not is_no_data_gap(g)]
        if dropped:
            gaps.append(
                Gap(
                    source=gap_source,
                    reason="error",
                    detail=f"{dropped} finding(s) dropped: citation not seen in retrieved items",
                )
            )
    gaps = gaps[:12]
    emit(
        "subagent_done",
        agent=agent,
        findings_count=sum(1 for f in findings if isinstance(f, FactSentence)),
        gaps=[g.model_dump(mode="json") for g in gaps],
        duration_ms=duration_ms,
    )
    span.set(findings=len(findings))
    span.end()
    return AgentReport(
        agent, "done", findings, gaps, flags=result.flags, budget_cut=result.status == "budget"
    )

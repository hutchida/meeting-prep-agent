"""The four sub-agents: each is a prompt, a read-only tool set and one run of the agent loop."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal, cast

from mpa.agents.context import AGENT_NAMES, GAP_SOURCE, MeetingContext
from mpa.agents.prompts import goal, system_prompt, user_task
from mpa.agents.tools import build_registry
from mpa.contract import RunDeps, Span
from mpa.contract.models import FactSentence, Gap, NoteSentence
from mpa.guardrails.injection import InjectionFlag
from mpa.loop import Budget, run_agent_loop
from mpa.loop.budget import Emit
from mpa.loop.events import clip
from mpa.loop.runner import LoopResult, SeenItem

__all__ = ["AGENT_NAMES", "AgentReport", "run_subagent"]

Reason = Literal["timeout", "fault_injected", "budget", "error"]
MAX_SALVAGE = 6


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
        assert result.output is not None
        gaps = list(result.output.gaps)
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

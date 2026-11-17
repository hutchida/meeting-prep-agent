"""run_briefing: resolve the meeting, run four sub-agents in parallel, write, verify, stream."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

from mpa.agents.context import (
    AGENT_LABEL,
    AGENT_NAMES,
    AGENT_SECTIONS,
    MeetingContext,
)
from mpa.agents.prompts import goal
from mpa.agents.resolve import Resolution, resolve_meeting
from mpa.agents.subagents import AgentReport, run_subagent
from mpa.agents.writer import collect_findings, with_meeting_line, write_briefing
from mpa.contract import AgentEvent, BriefingRequest, RunDeps, json_bytes
from mpa.contract.assemble import SECTION_IDS, SECTION_TITLES
from mpa.contract.models import FactSentence, NoteSentence
from mpa.guardrails.faults import FaultInjectingDataSource
from mpa.guardrails.verifier import Key, VerifiedSection, Verifier, VerifierReport
from mpa.loop import Budget, EventEmitter
from mpa.loop.events import clip

log = logging.getLogger(__name__)

SECTION_EVENT_BUDGET = 7000
PACK_BUDGET = 36000
_SHORT = {
    "correspondence": "Email and chat",
    "documents": "Documents",
    "news": "News",
    "attendees": "Attendee information",
}
_MISSING = {
    "meeting_at_a_glance": "meeting details",
    "client_snapshot": "document background",
    "recent_news": "recent news",
    "where_we_left_off": "recent correspondence",
    "open_items": "open items from email and chat",
    "attendees": "attendee details",
    "talking_points_and_risks": "talking points",
}
_EMPTY = {
    "meeting_at_a_glance": "No meeting details could be retrieved.",
    "client_snapshot": "No client background was found in the documents.",
    "recent_news": "No recent news found about {client}.",
    "where_we_left_off": "No recent correspondence found.",
    "open_items": "No open items found.",
    "attendees": "No attendee information found.",
    "talking_points_and_risks": "No talking points could be drawn from the available sources.",
}
PLACEHOLDER_MEETING = "M0"


def new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


async def run_briefing(request: BriefingRequest, deps: RunDeps) -> AsyncIterator[AgentEvent]:
    """Yield the run's events as they happen; the last one is always `run_done`."""
    queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
    emit = EventEmitter(new_run_id(), queue.put_nowait)
    producer = asyncio.create_task(_produce(request, deps, emit, queue))
    try:
        while (event := await queue.get()) is not None:
            yield event
    finally:
        if not producer.done():
            producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)


async def _produce(
    request: BriefingRequest,
    deps: RunDeps,
    emit: EventEmitter,
    queue: asyncio.Queue[AgentEvent | None],
) -> None:
    start = asyncio.get_running_loop().time()
    budget = Budget(
        deps.settings.max_steps_per_agent, deps.settings.max_tokens, deps.settings.max_cost_usd
    )
    try:
        await _pipeline(request, deps, emit, budget, start)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("run failed unexpectedly")
        _emergency_finish(emit, budget, start)
    finally:
        deps.tracer.flush()
        queue.put_nowait(None)


def _stats(budget: Budget, start: float) -> dict[str, Any]:
    return {
        "steps": budget.total_steps,
        "tokens_in": budget.tokens_in,
        "tokens_out": budget.tokens_out,
        "cost_usd": round(budget.cost_usd, 6),
        "duration_ms": round((asyncio.get_running_loop().time() - start) * 1000),
    }


def _section_dict(
    section_id: str, sentences: Sequence[FactSentence | NoteSentence]
) -> dict[str, Any]:
    return {
        "id": section_id,
        "title": SECTION_TITLES[section_id],
        "sentences": [s.model_dump(mode="json", exclude_none=True) for s in sentences],
        "empty": not any(isinstance(s, FactSentence) for s in sentences),
    }


def _emit_drafts(emit: EventEmitter, sections: list[dict[str, Any]]) -> None:
    for i, section in enumerate(sections):
        emit("draft", sections=[section], complete=i == len(sections) - 1)


def _note(text: str, citations: list[Key] | None = None) -> NoteSentence:
    return NoteSentence.model_validate(
        {
            "text": clip(text, 600),
            "citations": [{"type": t, "id": i} for t, i in (citations or [])],
            "kind": "note",
        }
    )


def _emergency_finish(emit: EventEmitter, budget: Budget, start: float) -> None:
    done = emit.counts
    if not done["run_started"]:
        emit("run_started", message="", model="unknown")
    if not done["plan"]:
        emit(
            "plan",
            client="Unknown",
            meeting_id=PLACEHOLDER_MEETING,
            meeting_title="Meeting not identified",
            meeting_start="1970-01-01T00:00:00Z",
            tasks=[],
        )
    if not done["verifier_result"]:
        emit(
            "verifier_result",
            verifier={"sentences_total": 0, "sentences_kept": 0, "sentences_dropped": 0},
            dropped=[],
        )
    if done["draft"] < len(SECTION_IDS):
        text = "The briefing could not be completed because of an internal error."
        sections = [_section_dict(i, [_note(text)]) for i in SECTION_IDS[done["draft"] :]]
        _emit_drafts(emit, sections)
    emit("run_done", partial=True, stats=_stats(budget, start))


async def _pipeline(
    request: BriefingRequest, deps: RunDeps, emit: EventEmitter, budget: Budget, start: float
) -> None:
    settings = deps.settings
    root = deps.tracer.start_run(
        emit.run_id, name="briefing", input={"message": clip(request.message, 500)}
    )
    emit("run_started", message=clip(request.message, 2000), model=settings.llm_model)
    resolution = await resolve_meeting(request.message, deps.data, settings)
    if resolution.context is None:
        _finish_unresolved(emit, resolution, budget, start, settings.demo_now.isoformat())
        root.end(error="meeting not resolved")
        return
    ctx = resolution.context

    fail = request.fail_source or settings.fail_source
    data = FaultInjectingDataSource(deps.data, fail) if fail else deps.data
    agent_deps = RunDeps(llm=deps.llm, data=data, tracer=deps.tracer, settings=settings)

    emit(
        "plan",
        client=clip(ctx.client, 100),
        meeting_id=ctx.meeting.id,
        meeting_title=clip(ctx.meeting.title, 200),
        meeting_start=ctx.meeting.start,
        tasks=[{"agent": a, "goal": clip(goal(a, ctx), 300)} for a in AGENT_NAMES],
    )
    reports = await _run_agents(ctx, agent_deps, budget, emit, root)

    flags: dict[Key, list[str]] = {}
    for report in reports.values():
        for flag in report.flags:
            flags.setdefault((flag.source_type, flag.source_id), []).append(flag.span)
    findings = collect_findings(ctx, reports, set(flags))
    unavailable = [
        AGENT_LABEL[a]
        for a in AGENT_NAMES
        if reports[a].status == "failed" or reports[a].budget_cut
    ]

    writer_span = deps.tracer.start_span(root, "writer", kind="agent")
    written = await write_briefing(
        ctx=ctx,
        findings=findings,
        unavailable=unavailable,
        llm=deps.llm,
        budget=budget,
        tracer=deps.tracer,
        span=writer_span,
        emit=emit,
    )
    writer_span.set(mode=written.mode, reason=written.reason)
    writer_span.end()

    allowed = {c for f in findings for c in f.citations}
    allowed |= {("cal", ctx.meeting.id), *(("contact", p.id) for p in ctx.people)}
    verify_span = deps.tracer.start_span(root, "verifier", kind="step")
    vr = await Verifier(
        deps.data,
        flagged=flags,
        allowed=allowed,
        llm=deps.llm,
        budget=budget,
        emit=emit,
    ).verify(with_meeting_line(written.sections, findings))
    verify_span.set(total=vr.total, kept=vr.kept)
    verify_span.end()

    sections = _finalize(vr, ctx, reports, flags)
    emit(
        "verifier_result",
        verifier={
            "sentences_total": vr.total,
            "sentences_kept": vr.kept,
            "sentences_dropped": vr.dropped_count,
        },
        dropped=[d.model_dump(mode="json") for d in vr.dropped[:10]],
    )
    _emit_drafts(emit, sections)
    partial = budget.hit_reported or any(
        r.status == "failed" or r.gaps or r.budget_cut for r in reports.values()
    )
    emit("run_done", partial=partial, stats=_stats(budget, start))
    root.end()


async def _run_agents(
    ctx: MeetingContext, deps: RunDeps, budget: Budget, emit: EventEmitter, root: Any
) -> dict[str, AgentReport]:
    tasks = {
        a: asyncio.create_task(run_subagent(a, ctx, deps, budget, emit, root), name=f"agent-{a}")
        for a in AGENT_NAMES
    }
    try:
        await asyncio.wait(tasks.values())
    except asyncio.CancelledError:
        for t in tasks.values():
            t.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        raise
    reports: dict[str, AgentReport] = {}
    for agent, task in tasks.items():
        if not task.cancelled() and task.exception() is None:
            reports[agent] = task.result()
            continue
        error = "cancelled" if task.cancelled() else f"unexpected {type(task.exception()).__name__}"
        emit("subagent_failed", agent=agent, reason="error", error=error)
        reports[agent] = AgentReport(agent, "failed", reason="error", error=error)
    return reports


def _failure_note(section_id: str, agent: str, report: AgentReport) -> str:
    short = _SHORT[agent]
    if report.reason == "timeout":
        head = f"{short} timed out"
    elif report.reason == "budget":
        head = f"{short} was stopped by the run budget"
    else:
        head = f"{short} could not be reached"
    return f"{head}; {_MISSING[section_id]} is not included in this briefing."


def _finalize(
    report: VerifierReport,
    ctx: MeetingContext,
    reports: dict[str, AgentReport],
    flags: dict[Key, list[str]],
) -> list[dict[str, Any]]:
    section_agents: dict[str, list[str]] = {}
    for agent, section_ids in AGENT_SECTIONS.items():
        for sid in section_ids:
            section_agents.setdefault(sid, []).append(agent)
    out: list[dict[str, Any]] = []
    for vs in report.sections:
        sentences: list[FactSentence | NoteSentence] = list(vs.sentences)
        explained = False
        for agent in section_agents.get(vs.id, []):
            r = reports[agent]
            if r.status == "failed":
                sentences.append(_note(_failure_note(vs.id, agent, r)))
                explained = True
            elif r.budget_cut:
                text = (
                    f"{_SHORT[agent]} was cut short by the run budget; section may be incomplete."
                )
                sentences.append(_note(text))
                explained = True
        if vs.id == "talking_points_and_risks":
            for key in sorted(flags):
                sentences.append(
                    _note(f"Source {key[1]} contains instructions that were ignored.", [key])
                )
        if not explained and not any(isinstance(s, FactSentence) for s in sentences):
            if report.dropped_in(vs.id):
                text = (
                    "Every statement drafted for this section failed verification and was removed."
                )
            else:
                text = _EMPTY[vs.id].format(client=ctx.client)
            sentences.insert(0, _note(text))
        out.append(_section_dict(vs.id, sentences))
    return _fit(out)


def _fit(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop trailing fact sentences until each draft event and the whole pack fit their caps."""

    def shrink(section: dict[str, Any]) -> bool:
        for i in range(len(section["sentences"]) - 1, -1, -1):
            if section["sentences"][i].get("kind") != "note":
                del section["sentences"][i]
                section["empty"] = not any(s.get("kind") != "note" for s in section["sentences"])
                return True
        return False

    for s in sections:
        while json_bytes(s) > SECTION_EVENT_BUDGET and shrink(s):
            pass
    while sum(json_bytes(s) for s in sections) > PACK_BUDGET:
        largest = max(sections, key=json_bytes)
        if not shrink(largest):
            break
    return sections


def _finish_unresolved(
    emit: EventEmitter, resolution: Resolution, budget: Budget, start: float, now: str
) -> None:
    emit(
        "plan",
        client=clip(resolution.client or "Unknown", 100),
        meeting_id=PLACEHOLDER_MEETING,
        meeting_title="Meeting not identified",
        meeting_start=now.replace("+00:00", "Z")[:19] + "Z",
        tasks=[],
    )
    problem = resolution.problem or "The meeting could not be identified."
    glance = [_note(f"I could not prepare a briefing: {problem}")]
    glance += [_note(f"Possible meeting: {c}") for c in resolution.candidates[:6]]
    glance.append(_note("Ask again with the client name and the day of the meeting."))
    sections = [_section_dict("meeting_at_a_glance", glance)]
    sections += [
        _section_dict(i, [_note("Not generated: the meeting could not be identified.")])
        for i in SECTION_IDS[1:]
    ]
    emit(
        "verifier_result",
        verifier={"sentences_total": 0, "sentences_kept": 0, "sentences_dropped": 0},
        dropped=[],
    )
    _emit_drafts(emit, sections)
    emit("run_done", partial=True, stats=_stats(budget, start))


__all__ = ["VerifiedSection", "run_briefing"]

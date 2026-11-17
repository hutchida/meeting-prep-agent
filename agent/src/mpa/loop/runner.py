"""The agent loop: model call -> tool calls (parallel) -> tool results -> ... -> submit_findings."""

from __future__ import annotations

import asyncio
import re
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from mpa.contract import (
    DataSourceError,
    LLMClient,
    LLMMessage,
    LLMResponse,
    Span,
    SubAgentOutput,
    ToolCall,
    ToolSpec,
    Tracer,
)
from mpa.contract.models import Gap
from mpa.guardrails.injection import InjectionFlag
from mpa.llm.errors import LLMError
from mpa.loop.budget import Budget, BudgetExceeded, Emit, report_budget_hit
from mpa.loop.events import clip
from mpa.loop.tools import ToolRegistry, event_args, shape_result

SUBMIT = "submit_findings"
_CITATION_TYPES = ["email", "chat", "doc", "news", "contact", "cal"]
_PREFIX_TYPE = {"E": "email", "C": "chat", "D": "doc", "N": "news", "P": "contact", "M": "cal"}
_REF_RE = re.compile(r"^(?:(email|chat|doc|news|contact|cal):)?([ECDNPM]\d{1,9})$")

SUBMIT_FINDINGS = ToolSpec(
    name=SUBMIT,
    description=(
        "Finish the task. Call this exactly once with your findings; it ends your work. "
        "Each finding is one factual sentence with citations to items you have seen."
    ),
    parameters={
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "One self-contained sentence."},
                        "citations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string", "enum": _CITATION_TYPES},
                                    "id": {"type": "string", "description": "For example E51"},
                                },
                                "required": ["type", "id"],
                            },
                        },
                    },
                    "required": ["text", "citations"],
                },
            },
            "gaps": {
                "type": "array",
                "description": "What you could not find or reach.",
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "enum": ["email", "chat", "docs", "news", "calendar", "contacts"],
                        },
                        "reason": {"type": "string", "enum": ["timeout", "error"]},
                        "detail": {"type": "string"},
                    },
                    "required": ["source", "reason", "detail"],
                },
            },
        },
        "required": ["findings"],
    },
)


@dataclass
class SeenItem:
    type: str
    id: str
    title: str
    text: str


@dataclass
class LoopResult:
    status: Literal["done", "budget", "failed"]
    output: SubAgentOutput | None = None
    reason: Literal["timeout", "fault_injected", "budget", "error"] | None = None
    error: str | None = None
    degraded: bool = False
    steps: int = 0
    flags: list[InjectionFlag] = field(default_factory=list)
    seen: dict[tuple[str, str], SeenItem] = field(default_factory=dict)


@dataclass
class _Outcome:
    text: str
    ok: bool
    transient: bool = False
    reason: Literal["timeout", "fault_injected", "error"] = "error"
    message: str = ""


def _coerce_ref(ref: Any) -> Any:
    if isinstance(ref, str) and (m := _REF_RE.match(ref.strip())):
        return {"type": m.group(1) or _PREFIX_TYPE[m.group(2)[0]], "id": m.group(2)}
    return ref


def coerce_submission(agent: str, args: dict[str, Any]) -> SubAgentOutput:
    """Validate `submit_findings` arguments; accepts "email:E1"-style citation strings."""
    if "_invalid_arguments" in args:
        raise ValueError("arguments were not valid JSON")
    findings = []
    for f in args.get("findings") or []:
        if isinstance(f, dict):
            f = dict(f)
            if isinstance(f.get("text"), str):
                f["text"] = clip(f["text"], 600)
            if isinstance(f.get("citations"), list):
                f["citations"] = [_coerce_ref(c) for c in f["citations"]]
            if f.get("kind") == "fact":
                f.pop("kind")
        findings.append(f)
    return SubAgentOutput.model_validate(
        {"agent": agent, "findings": findings, "gaps": args.get("gaps") or []}
    )


def describe_errors(err: Exception) -> str:
    if isinstance(err, ValidationError):
        parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in err.errors()[:4]]
        return clip("; ".join(parts), 500)
    return clip(str(err), 500)


def _record_seen(seen: dict[tuple[str, str], SeenItem], items: list[dict[str, Any]]) -> None:
    for item in items:
        if "id" in item and "type" in item:
            body = (
                item.get("body")
                or item.get("text")
                or item.get("snippet")
                or item.get("description")
                or item.get("notes")
                or ""
            )
            title = item.get("title") or item.get("subject") or item.get("name") or ""
            seen[(str(item["type"]), str(item["id"]))] = SeenItem(
                str(item["type"]), str(item["id"]), str(title), str(body)
            )


async def run_agent_loop(
    *,
    agent: str,
    llm: LLMClient,
    system_prompt: str,
    user_task: str,
    registry: ToolRegistry,
    budget: Budget,
    emit: Emit,
    tracer: Tracer,
    span: Span,
    gap_source: Literal["email", "chat", "docs", "news", "calendar", "contacts"],
    max_tokens: int = 3000,
    tool_timeout_s: float = 10.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> LoopResult:
    messages = [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(role="user", content=user_task),
    ]
    result = LoopResult(status="failed")
    call_counter = 0
    successes = 0
    validation_failures = 0
    nudged = False
    prefix = agent[:4]

    def degrade(why: str) -> LoopResult:
        result.status = "done"
        result.degraded = True
        result.output = SubAgentOutput(
            agent=agent,  # type: ignore[arg-type]
            findings=[],
            gaps=[Gap(source=gap_source, reason="error", detail=clip(why, 300))],
        )
        return result

    async def execute(call: ToolCall) -> _Outcome:
        tool = registry.get(call.name)
        if tool is None:
            emit(
                "tool_call",
                agent=agent,
                call_id=call.id,
                tool=clip(call.name, 64) or "unknown",
                args=event_args(call.arguments),
            )
            return _Outcome(f"ERROR: unknown tool {call.name!r}. Use only the listed tools.", False)
        emit(
            "tool_call",
            agent=agent,
            call_id=call.id,
            tool=call.name,
            args=event_args(call.arguments),
        )
        tool_span = tracer.start_span(span, call.name, kind="tool", input=call.arguments)
        loop = asyncio.get_running_loop()
        started = loop.time()
        outcome: _Outcome | None = None
        shaped = None
        for attempt in (1, 2):
            try:
                async with asyncio.timeout(tool_timeout_s):
                    value = await tool.handler(call.arguments)
                shaped = shape_result(call.name, value)
                break
            except KeyError as exc:
                outcome = _Outcome(f"ERROR: not found: {clip(str(exc), 120)}", False)
                break
            except (ValueError, TypeError) as exc:
                outcome = _Outcome(f"ERROR: invalid arguments: {clip(str(exc), 200)}", False)
                break
            except (DataSourceError, TimeoutError) as exc:
                if isinstance(exc, TimeoutError):
                    reason: Literal["timeout", "fault_injected", "error"] = "timeout"
                    message = f"{call.name} timed out"
                else:
                    injected = getattr(exc, "injected", False)
                    reason = "fault_injected" if injected else "error"
                    message = clip(str(exc) or type(exc).__name__, 250)
                if attempt == 1:
                    backoff_ms = 250 + zlib.crc32(call.id.encode()) % 100
                    emit(
                        "retry",
                        agent=agent,
                        attempt=1,
                        backoff_ms=backoff_ms,
                        error=clip(message, 300),
                    )
                    await sleep(backoff_ms / 1000)
                    continue
                outcome = _Outcome(
                    f"ERROR: {call.name} failed after a retry ({message}). The source may be "
                    "unavailable; continue with other tools or submit_findings and list a gap.",
                    False,
                    transient=True,
                    reason=reason,
                    message=message,
                )
        duration_ms = round((loop.time() - started) * 1000)
        if shaped is not None:
            result.flags.extend(shaped.flags)
            _record_seen(result.seen, shaped.items)
            emit(
                "tool_result",
                agent=agent,
                call_id=call.id,
                tool=call.name,
                ok=True,
                item_count=len(shaped.items),
                ids=shaped.ids,
                summary=shaped.summary,
                duration_ms=duration_ms,
            )
            tool_span.end()
            return _Outcome(shaped.text, True)
        assert outcome is not None
        emit(
            "tool_result",
            agent=agent,
            call_id=call.id,
            tool=call.name,
            ok=False,
            item_count=0,
            ids=[],
            summary=clip(outcome.message or outcome.text, 300),
            duration_ms=duration_ms,
        )
        tool_span.end(error=clip(outcome.text, 200))
        return outcome

    while True:
        try:
            step = budget.begin_step(agent)
        except BudgetExceeded as hit:
            report_budget_hit(budget, hit, emit)
            result.status = "budget"
            result.reason = "budget"
            result.error = f"{hit.kind} budget reached before {agent} finished"
            return result
        result.steps = step
        last_step = step >= budget.max_steps_per_agent
        offered = [SUBMIT_FINDINGS] if last_step else [*registry.specs(), SUBMIT_FINDINGS]
        try:
            response: LLMResponse = await llm.chat(
                messages,
                tools=offered,
                temperature=0.0,
                max_tokens=max_tokens,
                tag=f"{agent}:step{step}",
            )
        except LLMError as err:
            result.status = "failed"
            result.reason = "error"
            result.error = clip(str(err), 300)
            return result
        budget.charge(response.usage)
        tracer.record_llm(
            span,
            model=response.model,
            input=[m.model_dump(mode="json", exclude_none=True) for m in messages],
            output=response.message.model_dump(mode="json", exclude_none=True),
            usage=response.usage,
            latency_ms=response.latency_ms,
        )

        calls: list[ToolCall] = []
        for raw in response.message.tool_calls or []:
            call_counter += 1
            calls.append(
                ToolCall(id=f"{prefix}_{call_counter}", name=raw.name, arguments=raw.arguments)
            )
        messages.append(
            LLMMessage(role="assistant", content=response.message.content, tool_calls=calls or None)
        )

        if not calls:
            if nudged or last_step:
                return degrade("the model did not return findings")
            nudged = True
            messages.append(
                LLMMessage(role="user", content="Call submit_findings now with what you have.")
            )
            continue

        submit = next((c for c in calls if c.name == SUBMIT), None)
        if submit is not None:
            try:
                result.output = coerce_submission(agent, submit.arguments)
                result.status = "done"
                return result
            except (ValidationError, ValueError) as err:
                if validation_failures >= 1 or last_step:
                    return degrade(f"findings failed validation: {describe_errors(err)}")
                validation_failures += 1
                for c in calls:
                    note = (
                        f"ERROR: submit_findings arguments are invalid: {describe_errors(err)}. "
                        "Fix them and call submit_findings again."
                        if c is submit
                        else "Not executed. Call submit_findings on its own."
                    )
                    messages.append(
                        LLMMessage(role="tool", tool_call_id=c.id, name=c.name, content=note)
                    )
                continue

        outcomes = await asyncio.gather(*(execute(c) for c in calls))
        for call, outcome in zip(calls, outcomes, strict=True):
            messages.append(
                LLMMessage(role="tool", tool_call_id=call.id, name=call.name, content=outcome.text)
            )
        successes += sum(1 for o in outcomes if o.ok)
        stuck = [o for o in outcomes if not o.ok and o.transient]
        if successes == 0 and stuck and len(stuck) == len(outcomes):
            result.status = "failed"
            result.reason = stuck[-1].reason
            result.error = stuck[-1].message
            return result

"""Failure, budget, timeout and attack scenarios for run_briefing."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from mpa.contract import AgentEvent, BriefingRequest, LLMMessage, assemble_pack, check_event_order
from mpa.llm import RecordingClient, ReplayClient
from test_agents_fakes import FakeData, FlakyData, PolicyLLM, collect, make_deps, raw

BRIGHT = BriefingRequest(message="Prep me for my Thursday meeting with Brightmoor Renewables")
HALDEN = BriefingRequest(message="Prep me for the Halden Pay checkpoint on Wednesday")


def of(events: list[AgentEvent], type_: str) -> list[dict[str, Any]]:
    return [raw(e) for e in events if e.root.type == type_]


def section(pack: Any, sid: str) -> Any:
    return next(s for s in pack.sections if s.id == sid)


def texts(sec: Any) -> list[str]:
    return [s.text for s in sec.sentences]


@pytest.mark.parametrize("fail", ["news", "email", "docs", "all"])
async def test_fault_injection_still_finishes_with_a_partial_briefing(fail: str) -> None:
    request = BriefingRequest(message=BRIGHT.message, fail_source=fail)  # type: ignore[arg-type]
    events = await collect(request, make_deps(PolicyLLM()))
    assert check_event_order(events) == []
    assert events[-1].root.type == "run_done" and raw(events[-1])["partial"] is True
    pack = assemble_pack(events)
    agents = {"news": ["news"], "email": ["correspondence"], "docs": ["documents"],
              "all": ["correspondence", "documents", "news", "attendees"]}[fail]  # fmt: skip
    failed = {e["agent"]: e for e in of(events, "subagent_failed")}
    assert sorted(failed) == sorted(agents)
    assert all(e["reason"] == "fault_injected" for e in failed.values())
    for agent in agents:
        kinds = [
            e.root.type for e in events
            if getattr(e.root, "agent", None) == agent and e.root.type in
            {"tool_call", "retry", "tool_result", "subagent_failed"}
        ]  # fmt: skip
        assert kinds[0] == "tool_call" and kinds.index("retry") < kinds.index("tool_result")
        assert kinds[-1] == "subagent_failed"
    assert {g.reason for g in pack.gaps} == {"fault_injected"}
    assert pack.partial
    assert len(pack.sections) == 7
    messages = {
        "news": ("recent_news", "News could not be reached"),
        "email": ("where_we_left_off", "Email and chat could not be reached"),
        "docs": ("client_snapshot", "Documents could not be reached"),
    }
    if fail in messages:
        sid, text = messages[fail]
        assert text in " ".join(texts(section(pack, sid)))
        healthy = [
            s for s in pack.sections if s.id not in {sid, "open_items", "talking_points_and_risks"}
        ]
        assert any(not s.empty for s in healthy)
    else:
        assert "Attendee information could not be reached" in " ".join(
            texts(section(pack, "attendees"))
        )
        assert not section(pack, "meeting_at_a_glance").empty


async def test_fail_source_from_settings_is_used_when_request_has_none() -> None:
    events = await collect(BRIGHT, make_deps(PolicyLLM(), fail_source="news"))
    assert [e["agent"] for e in of(events, "subagent_failed")] == ["news"]


async def test_transient_source_error_is_retried_and_the_agent_recovers() -> None:
    events = await collect(BRIGHT, make_deps(PolicyLLM(), data=FlakyData("search_docs", 1)))
    assert [e["agent"] for e in of(events, "retry")] == ["documents"]
    assert of(events, "subagent_failed") == []
    assert raw(events[-1])["partial"] is False


@pytest.mark.parametrize(
    ("overrides", "kind"),
    [
        ({"max_tokens": 3000}, "tokens"),
        ({"max_cost_usd": 0.002}, "cost"),
        ({"max_steps_per_agent": 1}, "steps"),
    ],
)
async def test_budget_hit_stops_cleanly_with_named_gaps(
    overrides: dict[str, Any], kind: str
) -> None:
    llm = PolicyLLM()
    events = await collect(BRIGHT, make_deps(llm, **overrides))
    assert check_event_order(events) == []
    hits = of(events, "budget_hit")
    assert len(hits) == 1 and hits[0]["budget"] == kind
    pack = assemble_pack(events)
    assert pack.partial
    assert {g.reason for g in pack.gaps} == {"budget"}
    assert {g.source for g in pack.gaps} >= {"email", "docs", "news"}
    assert len(pack.sections) == 7
    assert "run budget" in " ".join(texts(section(pack, "recent_news")))
    assert "writer" not in "".join(llm.tags) or kind == "steps"
    assert all(raw(e)["ts"] for e in events)


async def test_writer_runs_in_degraded_mode_when_budget_is_gone() -> None:
    llm = PolicyLLM()
    events = await collect(BRIGHT, make_deps(llm, max_tokens=3000))
    assert "writer" not in llm.tags
    pack = assemble_pack(events)
    assert not section(pack, "meeting_at_a_glance").empty
    assert any(not s.empty for s in pack.sections)


class Selective(PolicyLLM):  # type: ignore[misc]
    """Misbehaves for one agent only."""

    def __init__(self, agent: str, how: str, **kw: Any) -> None:
        super().__init__(**kw)
        self.agent, self.how = agent, how

    async def chat(self, messages: list[LLMMessage], **kw: Any) -> Any:
        if (kw.get("tag") or "").startswith(self.agent):
            if self.how == "hang":
                await asyncio.sleep(30)
            if self.how == "cancel":
                raise asyncio.CancelledError
            if self.how == "crash":
                raise RuntimeError("boom with /secret/path")
        return await super().chat(messages, **kw)


async def test_subagent_timeout_does_not_stop_the_others() -> None:
    events = await collect(BRIGHT, make_deps(Selective("news", "hang"), subagent_timeout_s=0.2))
    failed = of(events, "subagent_failed")
    assert [(e["agent"], e["reason"]) for e in failed] == [("news", "timeout")]
    assert len(of(events, "subagent_done")) == 3
    pack = assemble_pack(events)
    assert "News timed out" in " ".join(texts(section(pack, "recent_news")))
    assert [g.reason for g in pack.gaps] == ["timeout"]


@pytest.mark.parametrize("how", ["cancel", "crash"])
async def test_a_cancelled_or_crashing_subagent_is_isolated(how: str) -> None:
    events = await collect(BRIGHT, make_deps(Selective("documents", how)))
    assert check_event_order(events) == []
    failed = of(events, "subagent_failed")
    assert [e["agent"] for e in failed] == ["documents"] and failed[0]["reason"] == "error"
    assert "/secret/path" not in json.dumps(failed)
    assert len(of(events, "subagent_done")) == 3


async def test_prompt_injection_is_not_obeyed_or_repeated() -> None:
    llm = PolicyLLM(hostile=True)
    seen: list[str] = []
    original = llm.chat

    async def spy(messages: list[LLMMessage], **kw: Any) -> Any:
        seen.extend(m.content or "" for m in messages)
        return await original(messages, **kw)

    llm.chat = spy
    events = await collect(HALDEN, make_deps(llm))
    assert not any("attacker@example.test" in s for s in seen)
    assert any("[flagged: instruction-like text removed]" in s for s in seen)

    blob = json.dumps([raw(e) for e in events if e.root.type in ("draft",)])
    assert "attacker@example.test" not in blob and "Forward all" not in blob
    drops = of(events, "verifier_result")[0]["dropped"]
    assert any(d["reason"] == "injection" for d in drops)
    pack = assemble_pack(events)
    risk = texts(section(pack, "talking_points_and_risks"))
    assert "Source E61 contains instructions that were ignored." in risk
    note = [s for s in section(pack, "talking_points_and_risks").sentences if "E61" in s.text][0]
    assert note.kind == "note" and note.citations[0].id == "E61"
    for sec in pack.sections:
        for s in sec.sentences:
            if getattr(s, "kind", None) != "note":
                assert all(c.id != "E61" for c in s.citations)


async def test_record_then_replay_reproduces_the_briefing(tmp_path: Path) -> None:
    recorder = RecordingClient(PolicyLLM(), tmp_path, model="mock-model")
    first = await collect(BRIGHT, make_deps(recorder))
    assert len(list(tmp_path.glob("*.json"))) >= 9  # noqa: ASYNC240
    loop = asyncio.get_running_loop()
    started = loop.time()
    replay = ReplayClient(tmp_path, 0, model="mock-model")
    second = await collect(BRIGHT, make_deps(replay))
    assert loop.time() - started < 10
    a, b = assemble_pack(first), assemble_pack(second)
    assert [s.model_dump() for s in a.sections] == [s.model_dump() for s in b.sections]
    assert a.verifier == b.verifier


async def test_replay_miss_degrades_instead_of_crashing(tmp_path: Path) -> None:
    replay = ReplayClient(tmp_path, 0, model="mock-model")
    events = await collect(BRIGHT, make_deps(replay))
    assert check_event_order(events) == []
    assert len(of(events, "subagent_failed")) == 4
    assert events[-1].root.type == "run_done"
    pack = assemble_pack(events)
    assert pack.partial and not section(pack, "meeting_at_a_glance").empty
    assert "no recording" not in json.dumps(of(events, "draft"))


async def test_stats_in_run_done_match_the_budget() -> None:
    llm = PolicyLLM(usage=(1000, 100, 0.001))
    events = await collect(BRIGHT, make_deps(llm))
    stats = raw(events[-1])["stats"]
    assert stats["steps"] == len(llm.tags)
    assert stats["tokens_in"] == 1000 * len(llm.tags) and stats["tokens_out"] == 100 * len(llm.tags)
    assert stats["cost_usd"] == pytest.approx(0.001 * len(llm.tags))


async def test_unknown_data_error_in_resolution_is_a_partial_briefing() -> None:
    class NoCalendar(FakeData):  # type: ignore[misc]
        async def get_calendar(self, **kw: Any) -> Any:
            from mpa.contract import DataSourceError

            raise DataSourceError("calendar down")

    events = await collect(BRIGHT, make_deps(PolicyLLM(), data=NoCalendar()))
    pack = assemble_pack(events)
    assert pack.partial and "calendar could not be reached" in " ".join(texts(pack.sections[0]))


async def test_replay_with_the_default_delay_stays_well_under_ten_seconds(tmp_path: Path) -> None:
    await collect(BRIGHT, make_deps(RecordingClient(PolicyLLM(), tmp_path, model="mock-model")))
    loop = asyncio.get_running_loop()
    started = loop.time()
    events = await collect(BRIGHT, make_deps(ReplayClient(tmp_path, 250, model="mock-model")))
    assert loop.time() - started < 10
    assert raw(events[-1])["partial"] is False


class SpyTracer:
    def __init__(self) -> None:
        self.runs: list[str] = []
        self.spans: list[tuple[str, str]] = []
        self.llm_calls = 0
        self.ended = 0
        self.flushed = 0

    def _span(self) -> Any:
        spy = self

        class S:
            def set(self, **attrs: Any) -> None:
                return None

            def end(self, *, error: str | None = None) -> None:
                spy.ended += 1

        return S()

    def start_run(self, run_id: str, *, name: str, input: dict[str, Any]) -> Any:
        self.runs.append(run_id)
        return self._span()

    def start_span(self, parent: Any, name: str, *, kind: str, input: Any = None) -> Any:
        self.spans.append((kind, name))
        return self._span()

    def record_llm(self, parent: Any, **kw: Any) -> None:
        self.llm_calls += 1

    def flush(self) -> None:
        self.flushed += 1


async def test_tracer_sees_the_run_agents_tools_and_every_model_call() -> None:
    from mpa.contract import RunDeps

    tracer = SpyTracer()
    llm = PolicyLLM()
    deps = RunDeps(llm=llm, data=FakeData(), tracer=tracer, settings=make_deps(llm).settings)
    events = await collect(BRIGHT, deps)
    assert len(tracer.runs) == 1 and tracer.flushed == 1
    kinds = [k for k, _ in tracer.spans]
    assert kinds.count("agent") == 5 and kinds.count("tool") == sum(
        1 for e in events if e.root.type == "tool_call"
    )
    assert tracer.llm_calls == len(llm.tags)
    assert tracer.ended >= len(tracer.spans)


async def test_an_unexpected_bug_still_ends_with_a_valid_stream() -> None:
    class Broken(PolicyLLM):  # type: ignore[misc]
        async def chat(self, messages: list[LLMMessage], **kw: Any) -> Any:
            if kw.get("tag") == "writer":
                raise RuntimeError("bug in the writer path")
            return await super().chat(messages, **kw)

    events = await collect(BRIGHT, make_deps(Broken()))
    assert check_event_order(events) == []
    assert events[-1].root.type == "run_done" and raw(events[-1])["partial"] is True
    pack = assemble_pack(events)
    assert "internal error" in " ".join(texts(pack.sections[1]))
    assert "bug in the writer" not in json.dumps([raw(e) for e in events])

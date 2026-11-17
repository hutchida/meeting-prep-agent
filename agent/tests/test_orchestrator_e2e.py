"""run_briefing end to end with a policy-driven mock model and an in-memory dataset."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from mpa.contract import BriefingRequest, assemble_pack, check_event_order, json_bytes
from mpa.contract.assemble import SECTION_IDS
from test_agents_fakes import PolicyLLM, collect, make_deps, raw

ROOT = Path(__file__).resolve().parents[2]
PACK_SCHEMA = Draft202012Validator(
    json.loads((ROOT / "packages/contract/schema/BriefingPack.json").read_text())
)
EVENT_SCHEMA = Draft202012Validator(
    json.loads((ROOT / "packages/contract/schema/AgentEvent.json").read_text())
)
REQUEST = BriefingRequest(message="Prep me for my Thursday meeting with Brightmoor Renewables")


async def test_full_run_event_order_and_pack() -> None:
    events = await collect(REQUEST, make_deps(PolicyLLM()))
    assert check_event_order(events) == []
    types = [e.root.type for e in events]
    assert types[:2] == ["run_started", "plan"]
    assert types.count("subagent_started") == 4
    assert types.count("subagent_done") == 4
    assert types[-9] == "verifier_result" and types[-1] == "run_done"
    assert types[-8:-1] == ["draft"] * 7

    pack = assemble_pack(events)
    assert [s.id for s in pack.sections] == list(SECTION_IDS)
    assert pack.client == "Brightmoor Renewables"
    assert pack.meeting.cal_id == "M2"
    assert pack.partial is False and pack.gaps == []
    facts = [
        s for sec in pack.sections for s in sec.sentences if getattr(s, "kind", None) != "note"
    ]
    assert facts and all(s.citations for s in facts)
    assert pack.verifier.sentences_kept >= len(facts) - 1
    PACK_SCHEMA.validate(pack.model_dump(mode="json", exclude_none=True))


async def test_events_are_small_and_schema_valid() -> None:
    events = await collect(REQUEST, make_deps(PolicyLLM()))
    for e in events:
        assert json_bytes(e) <= 8192
        EVENT_SCHEMA.validate(raw(e))
    assert json_bytes(assemble_pack(events)) <= 40960
    assert [e.root.seq for e in events] == list(range(len(events)))


async def test_plan_carries_meeting_fields() -> None:
    events = await collect(REQUEST, make_deps(PolicyLLM()))
    plan = raw(events[1])
    assert plan["meeting_id"] == "M2"
    assert plan["meeting_title"].startswith("Brightmoor Renewables")
    assert plan["meeting_start"] == "2026-03-12T14:00:00Z"
    assert [t["agent"] for t in plan["tasks"]] == [
        "correspondence",
        "documents",
        "news",
        "attendees",
    ]


async def test_subagents_run_concurrently() -> None:
    llm = PolicyLLM(delay=0.02)
    events = await collect(REQUEST, make_deps(llm))
    types = [(e.root.type, getattr(e.root, "agent", None)) for e in events]
    last_start = max(i for i, (t, _) in enumerate(types) if t == "subagent_started")
    first_done = min(i for i, (t, _) in enumerate(types) if t == "subagent_done")
    assert last_start < first_done
    assert llm.peak == 4


async def test_writer_prompt_is_deterministic() -> None:
    a, b = PolicyLLM(), PolicyLLM()
    seen: list[list[str]] = []
    for llm in (a, b):
        recorded: list[str] = []
        orig = llm.chat

        async def spy(messages, *, _orig=orig, _rec=recorded, **kw):  # type: ignore[no-untyped-def]
            _rec.append(json.dumps([m.model_dump(mode="json") for m in messages], sort_keys=True))
            return await _orig(messages, **kw)

        llm.chat = spy
        await collect(REQUEST, make_deps(llm))
        seen.append(sorted(recorded))
    assert seen[0] == seen[1]


@pytest.mark.parametrize(
    "message",
    [
        "Prep me for the Halden Pay checkpoint on Wednesday",
        "get me ready for Kettle and Crumb tomorrow week",
        "brief me on the brightmoor ppa meeting",
    ],
)
async def test_client_resolution_variants(message: str) -> None:
    events = await collect(BriefingRequest(message=message), make_deps(PolicyLLM()))
    assert check_event_order(events) == []
    assert raw(events[1])["meeting_id"] in {"M1", "M2", "M3"}


async def test_unresolved_request_gives_clear_partial_briefing() -> None:
    llm = PolicyLLM()
    events = await collect(BriefingRequest(message="Prep me for my meeting"), make_deps(llm))
    assert check_event_order(events) == []
    assert llm.tags == []
    pack = assemble_pack(events)
    assert pack.partial is True
    glance = " ".join(s.text for s in pack.sections[0].sentences)
    assert "could not prepare" in glance and "Halden Pay" in glance
    assert events[-1].root.type == "run_done"


async def test_wrong_weekday_for_client_is_explained() -> None:
    events = await collect(
        BriefingRequest(message="Prep me for Halden Pay on Friday"), make_deps(PolicyLLM())
    )
    pack = assemble_pack(events)
    text = " ".join(s.text for s in pack.sections[0].sentences)
    assert "No meeting with Halden Pay on Friday" in text and "Wednesday 11 March" in text


async def test_consumer_disconnect_cancels_everything() -> None:
    import asyncio

    from mpa.agents.orchestrator import run_briefing

    llm = PolicyLLM(delay=0.05)
    before = {t for t in asyncio.all_tasks()}
    gen = run_briefing(REQUEST, make_deps(llm))
    assert isinstance(gen, AsyncGenerator)
    async for event in gen:
        if event.root.type == "tool_call":
            break
    await gen.aclose()
    await asyncio.sleep(0)
    leftover = {t for t in asyncio.all_tasks() if not t.done()} - before
    assert not leftover
    calls_at_close = len(llm.tags)
    await asyncio.sleep(0.2)
    assert len(llm.tags) == calls_at_close

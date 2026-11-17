"""Writer parsing, the retry and the deterministic fallback; size fitting; resolution rules."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from mpa.agents.orchestrator import PACK_BUDGET, SECTION_EVENT_BUDGET, _fit
from mpa.agents.resolve import resolve_meeting
from mpa.agents.writer import (
    Finding,
    WriterFormatError,
    fallback_sections,
    parse_writer_json,
    write_briefing,
)
from mpa.contract import BriefingRequest, NoopTracer, NullSpan, assemble_pack, json_bytes
from mpa.contract.assemble import SECTION_IDS
from mpa.loop import Budget
from test_agents_fakes import FakeData, PolicyLLM, ScriptedLLM, collect, make_deps, reply, settings

NOW = datetime(2026, 3, 9, 9, 0, tzinfo=UTC)


def doc(sections: dict[str, list[Any]]) -> str:
    return json.dumps(
        {"sections": [{"id": i, "sentences": sections.get(i, [])} for i in SECTION_IDS]}
    )


def test_parse_accepts_type_prefixed_bare_and_inline_citations() -> None:
    raw = doc(
        {
            "client_snapshot": [
                {"text": "Fee is £62,000 [doc:D4].", "citations": ["email:E1", "D4", "doc:D4"]},
                {"text": "   ", "citations": ["doc:D4"]},
            ]
        }
    )
    sections = parse_writer_json("```json\n" + raw + "\n```")
    sent = sections[1].sentences
    assert len(sent) == 1 and sent[0].text == "Fee is £62,000 ."
    assert sent[0].citations == (("doc", "D4"), ("email", "E1"))
    assert [s.id for s in sections] == list(SECTION_IDS)


@pytest.mark.parametrize(
    "raw",
    [
        "no json at all",
        '{"sections": "x"}',
        json.dumps({"sections": [{"id": "meeting_at_a_glance", "sentences": []}]}),
        doc({"open_items": [{"text": "x", "citations": ["email:D4"]}]}),
        doc({"open_items": [{"text": "x", "citations": ["banana"]}]}),
        json.dumps({"sections": [{"id": "nope", "sentences": []}]}),
    ],
)
def test_parse_rejects_malformed_output(raw: str) -> None:
    with pytest.raises(WriterFormatError):
        parse_writer_json(raw)


def findings() -> list[Finding]:
    return [
        Finding("calendar", "Meeting: Q2 plan, Friday 13 March 2026.", (("cal", "M3"),)),
        Finding("documents", "Retainer is £12,000 a month.", (("doc", "D5"),)),
        Finding("news", "Kettle & Crumb launched a bar.", (("news", "N12"),)),
        Finding(
            "correspondence", "Tomás promised the margin model by 2 March.", (("email", "E44"),)
        ),
        Finding("correspondence", "Bea approved the packaging switch.", (("email", "E39"),)),
        Finding(
            "correspondence", "Bea wants £120,000 but Rohan plans £95,000.", (("email", "E35"),)
        ),
        Finding("attendees", "Bea is the founder.", (("contact", "P11"),)),
    ]


def test_fallback_writer_renders_every_section_without_a_model() -> None:
    sections = {s.id: s for s in fallback_sections(findings())}
    assert list(sections) == list(SECTION_IDS)
    texts = {k: [s.text for s in v.sentences] for k, v in sections.items()}
    assert texts["client_snapshot"] == ["Retainer is £12,000 a month."]
    assert texts["recent_news"] == ["Kettle & Crumb launched a bar."]
    assert texts["open_items"] == ["Tomás promised the margin model by 2 March."]
    assert "Bea approved the packaging switch." in texts["where_we_left_off"]
    assert texts["talking_points_and_risks"] == ["Bea wants £120,000 but Rohan plans £95,000."]
    assert texts["attendees"] == ["Bea is the founder."]
    assert all(s.citations for v in sections.values() for s in v.sentences)


async def run_writer(llm: Any, **budget: Any) -> Any:
    from test_agents_fakes import FakeData

    events: list[Any] = []
    cal = (await FakeData().get_calendar())[2]
    from mpa.agents.context import MeetingContext

    ctx = MeetingContext("Kettle & Crumb", cal, (), NOW)
    result = await write_briefing(
        ctx=ctx, findings=findings(), unavailable=[], llm=llm,
        budget=Budget(8, budget.get("tokens", 10**9), 1.0), tracer=NoopTracer(), span=NullSpan(),
        emit=lambda t, **f: events.append((t, f)),
    )  # fmt: skip
    return result, events


GOOD = doc({"client_snapshot": [{"text": "Retainer is £12,000 a month.", "citations": ["doc:D5"]}]})


async def test_writer_uses_the_model_output_when_valid() -> None:
    llm = ScriptedLLM([reply(content=GOOD)])
    result, _ = await run_writer(llm)
    assert result.mode == "llm" and len(llm.requests) == 1
    assert llm.requests[0]["tools"] == [] and llm.requests[0]["tag"] == "writer"


async def test_writer_retries_once_with_the_error_then_succeeds() -> None:
    llm = ScriptedLLM([reply(content="oops"), reply(content=GOOD)])
    result, _ = await run_writer(llm)
    assert result.mode == "llm" and len(llm.requests) == 2
    assert llm.requests[1]["tag"] == "writer:retry"
    assert "rejected: no JSON object found" in llm.requests[1]["messages"][-1].content


async def test_writer_falls_back_after_two_bad_outputs() -> None:
    llm = ScriptedLLM([reply(content="oops"), reply(content="still not json")])
    result, _ = await run_writer(llm)
    assert result.mode == "fallback" and "invalid" in (result.reason or "")
    assert any(s.sentences for s in result.sections)


async def test_writer_falls_back_on_llm_error_and_when_budget_is_gone() -> None:
    from mpa.llm import LLMError

    result, _ = await run_writer(ScriptedLLM([LLMError("boom")]))
    assert result.mode == "fallback"
    llm = ScriptedLLM([reply(content=GOOD)])
    result2, events = await run_writer(llm, tokens=0)
    assert result2.mode == "fallback" and llm.requests == []
    assert events[0][0] == "budget_hit"


async def test_hallucinated_writer_sentences_are_dropped_by_the_verifier() -> None:
    bad = doc(
        {
            "client_snapshot": [
                {"text": "The retainer is £99,000 a month.", "citations": ["doc:D5"]},
                {"text": "The retainer is £12,000 a month.", "citations": ["doc:D5"]},
                {"text": "Rohan resigned last Tuesday.", "citations": ["email:E9999"]},
                {"text": "No citation here.", "citations": []},
            ]
        }
    )
    llm = PolicyLLM(writer_text=bad)
    events = await collect(BriefingRequest(message="Prep me for Kettle and Crumb"), make_deps(llm))
    result = [e for e in events if e.root.type == "verifier_result"][0].root
    reasons = sorted(d.reason for d in result.dropped)  # type: ignore[union-attr]
    assert reasons == ["invalid_citation", "no_citation", "unsupported"]
    pack = assemble_pack(events)
    assert [s.text for s in pack.sections[1].sentences if getattr(s, "kind", None) != "note"] == [
        "The retainer is £12,000 a month."
    ]


def test_fit_trims_sentences_to_the_event_and_pack_caps() -> None:
    fat = {"text": "x" * 590, "citations": [{"type": "email", "id": f"E{i}"} for i in range(8)]}
    note = {"text": "kept", "citations": [], "kind": "note"}
    sections = [
        {"id": i, "title": i, "sentences": [dict(fat) for _ in range(16)] + [note], "empty": False}
        for i in SECTION_IDS
    ]
    fitted = _fit(sections)
    assert all(json_bytes(s) <= SECTION_EVENT_BUDGET for s in fitted)
    assert sum(json_bytes(s) for s in fitted) <= PACK_BUDGET
    assert all(s["sentences"][-1] == note for s in fitted)


async def test_resolution_rules() -> None:
    cfg = settings()
    data = FakeData()

    async def ask(message: str) -> Any:
        return await resolve_meeting(message, data, cfg)

    r = await ask("prep me for Thursday")
    assert (
        r.context and r.context.meeting.id == "M2" and r.context.client == "Brightmoor Renewables"
    )
    assert [p.id for p in r.context.people] == ["P1", "P4", "P8", "P9"] and r.context.user
    r = await ask("Kettle & Crumb")
    assert r.context and r.context.meeting.id == "M3"
    r = await ask("what's next with halden?")
    assert r.context and r.context.meeting.id == "M1"
    r = await ask("prep me for my meeting")
    assert r.context is None and "which client" in (r.problem or "") and len(r.candidates) == 3
    r = await ask("meeting with Acme Corp on Monday")
    assert r.context is None and "Monday" in (r.problem or "")
    r = await ask("Prep me for Sunday")
    assert r.context is None

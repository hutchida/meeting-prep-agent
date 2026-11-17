"""Quality-pass behaviours: prompts, conflict hints, no-data gaps, the pre-Writer support filter."""

from __future__ import annotations

from typing import Any

from mpa.agents.orchestrator import PACK_BUDGET
from mpa.agents.prompts import WRITER_SYSTEM, system_prompt, writer_user
from mpa.agents.resolve import resolve_meeting
from mpa.agents.subagents import is_no_data_gap, run_subagent
from mpa.agents.writer import Finding, conflict_hints
from mpa.contract import NullSpan
from mpa.contract.models import Gap
from mpa.guardrails.verifier import RawSentence, Verifier
from mpa.loop import Budget
from test_agents_fakes import FakeData, ScriptedLLM, call, make_deps, reply, settings

PLANT = "Plant Alpha"


def finding(text: str, *cites: tuple[str, str], agent: str = "documents") -> Finding:
    return Finding(agent, text, cites)


def test_conflict_hints_pair_findings_with_different_figures_of_the_same_kind() -> None:
    fs = [
        finding(f"The {PLANT} wind site has a rated capacity of 40 MW.", ("doc", "D1")),
        finding(
            f"On 3 May 2026, the {PLANT} site capacity was changed to 35 MW.",
            ("chat", "C1"),
            agent="correspondence",
        ),
        finding("Maintenance budget for the depot is £8,000.", ("doc", "D2")),
        finding("The depot maintenance budget was approved at £10,000.", ("email", "E2")),
        finding("Fixed fee of £5,000 in two instalments.", ("doc", "D3")),
    ]
    hints = conflict_hints(fs)
    assert len(hints) == 2
    assert any("40 MW" in h and "35 MW" in h and "mw values" in h for h in hints)
    assert any("£8,000" in h and "£10,000" in h for h in hints)
    assert conflict_hints(fs) == hints


def test_conflict_hints_ignore_same_figures_same_source_and_unrelated_subjects() -> None:
    same = [
        finding("The depot maintenance budget is £8,000.", ("doc", "D2")),
        finding("The approved depot maintenance budget is £8,000.", ("email", "E2")),
    ]
    one_source = [
        finding("The depot maintenance budget is £8,000.", ("doc", "D2")),
        finding("The depot maintenance budget is later raised to £10,000.", ("doc", "D2")),
    ]
    unrelated = [
        finding("The depot maintenance budget is £8,000.", ("doc", "D2")),
        finding("Training programme costs £12,000 for the whole team.", ("doc", "D9")),
        finding("The meeting room was booked.", ("cal", "M1"), agent="calendar"),
    ]
    assert conflict_hints(same) == []
    assert conflict_hints(one_source) == []
    assert conflict_hints(unrelated) == []


def test_writer_user_lists_hints_only_when_there_are_some() -> None:
    cfg = settings()
    import asyncio

    ctx = asyncio.run(resolve_meeting("Prep me for Thursday", FakeData(), cfg)).context
    assert ctx is not None
    plain = writer_user(ctx, ["[documents] x | cites: doc:D1"], [])
    assert "CONFLICT HINTS" not in plain
    with_hints = writer_user(ctx, ["[documents] x | cites: doc:D1"], [], ["- a vs b"])
    assert "CONFLICT HINTS" in with_hints and "- a vs b" in with_hints


def test_writer_prompt_covers_contradictions_commitments_and_role_citations() -> None:
    for needle in ("Sources disagree on", "Commitment", "contact:P8", "exactly", "conflict hints"):
        assert needle.lower() in WRITER_SYSTEM.lower()
    assert "open_items" in WRITER_SYSTEM and PACK_BUDGET > 0


async def _ctx() -> Any:
    r = await resolve_meeting("Prep me for Thursday", FakeData(), settings())
    assert r.context is not None
    return r.context


async def test_agent_prompts_ask_for_commitments_dates_and_contact_citations() -> None:
    ctx = await _ctx()
    corr = system_prompt("correspondence", ctx)
    docs = system_prompt("documents", ctx)
    att = system_prompt("attendees", ctx)
    for text in (corr, docs):
        assert "Commitment:" in text and "Sources disagree:" in text
    assert "promise" in corr and "delivered" in corr and "search_chat" in corr
    assert "instalment" in docs and "payment" in docs
    assert "contact record" in att and "contact:P8" in att
    assert system_prompt("correspondence", ctx) == corr


def test_no_data_gaps_are_not_errors_but_outages_are() -> None:
    def gap(detail: str) -> Gap:
        return Gap(source="contacts", reason="error", detail=detail)

    assert is_no_data_gap(gap("Contact P99 could not be found."))
    assert is_no_data_gap(gap("No record exists for the second attendee: not found"))
    assert not is_no_data_gap(gap("Contact lookup failed after a retry (503)."))
    assert not is_no_data_gap(gap("Contacts service unavailable; not found anything"))
    assert not is_no_data_gap(gap("Search timed out"))


async def test_unsupported_marks_only_clearly_unsupported_sentences() -> None:
    ok = RawSentence(
        "Marcus says go-live is locked for 14 April 2026 and Kofi says engineering will ship "
        "on 28 April.",
        (("email", "E47"), ("chat", "C22")),
    )
    wrong = RawSentence("The fixed fee is £99,000 in four instalments.", (("doc", "D4"),))
    missing = RawSentence("Anything at all.", (("doc", "D9999"),))
    uncited = RawSentence("No citation.", ())
    flags = await Verifier(FakeData()).unsupported([ok, wrong, missing, uncited])
    assert flags == [False, True, False, False]


async def test_subagent_drops_unsupported_findings_and_no_data_gaps() -> None:
    ctx = await _ctx()
    findings = [
        {"text": "The fixed fee is £99,000 in four instalments.", "citations": [doc("D4")]},
        {"text": "Retainer is £12,000 a month for three months.", "citations": [doc("D5")]},
    ]
    gaps = [
        {"source": "docs", "reason": "error", "detail": "Document D404 could not be found."},
        {"source": "docs", "reason": "error", "detail": "Search failed after a retry (503)."},
    ]
    llm = ScriptedLLM(
        [
            reply(call("search_docs", query="Brightmoor")),
            reply(call("get_doc", id="D4", i=1), call("get_doc", id="D5", i=2)),
            reply(call("submit_findings", findings=findings, gaps=gaps)),
        ]
    )
    deps = make_deps(llm)
    events: list[tuple[str, dict[str, Any]]] = []
    report = await run_subagent(
        "documents", ctx, deps, Budget(8, 10**9, 1.0), lambda t, **f: events.append((t, f)),
        NullSpan(),
    )  # fmt: skip
    assert report.status == "done"
    assert [f.text for f in report.findings] == ["Retainer is £12,000 a month for three months."]
    assert [g.detail for g in report.gaps] == ["Search failed after a retry (503)."]


def doc(i: str) -> dict[str, str]:
    return {"type": "doc", "id": i}

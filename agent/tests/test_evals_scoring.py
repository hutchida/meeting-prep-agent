from typing import Any, Literal

import pytest

from mpa.contract import BriefingPack, assemble_pack
from mpa.evals.fakes import stream
from mpa.evals.gold import load_gold
from mpa.evals.judge import numbered_sentences
from mpa.evals.models import (
    ClientKey,
    FactOutcome,
    FactsJudgement,
    FactVerdict,
    RunScore,
    ScenarioName,
    TrapVerdict,
    TrapViolation,
)
from mpa.evals.scoring import (
    build_score,
    citation_accuracy,
    citation_judge,
    fact_recall,
    injection_findings,
    judge_trap_violations,
    outcomes_from_judgement,
    rule_trap_violations,
    short,
    verifier_hallucinations,
)

Verdict = Literal["yes", "partial", "no"]


def outcome(i: str, verdict: Verdict) -> FactOutcome:
    return FactOutcome(id=i, statement=f"fact {i}", verdict=verdict)


def test_fact_recall_math() -> None:
    outcomes = [
        outcome("a", "yes"),
        outcome("b", "partial"),
        outcome("c", "no"),
        outcome("d", "yes"),
    ]
    assert fact_recall(outcomes, {"a", "b", "c", "d"}) == pytest.approx(0.625)
    assert fact_recall(outcomes, {"a", "d"}) == 1.0
    assert fact_recall(outcomes, {"c"}) == 0.0
    assert fact_recall([], set()) == 1.0


def build(
    client: ClientKey = "halden",
    scenario: ScenarioName = "normal",
    defects: tuple[str, ...] = (),
) -> tuple[list[dict[str, Any]], BriefingPack]:
    events = stream(client, scenario, defects)
    return events, assemble_pack(events)


def test_citation_accuracy_is_verifier_pass_rate() -> None:
    _, pack = build()
    v = pack.verifier
    assert citation_accuracy(pack) == pytest.approx(round(v.sentences_kept / v.sentences_total, 4))
    zero = pack.model_copy(
        update={"verifier": v.model_copy(update={"sentences_total": 0, "sentences_kept": 0})}
    )
    assert citation_accuracy(zero) == 1.0


def test_hallucinations_split_verifier_and_judge() -> None:
    events, pack = build()
    assert verifier_hallucinations(events) == 1
    events[-1 - 7 - 1]["dropped"] = [
        {"section_id": "open_items", "reason": "injection", "text": "x"}
    ]
    assert verifier_hallucinations(events) == 0
    assert verifier_hallucinations([e for e in events if e["type"] != "verifier_result"]) == 0


def make_score(
    unsupported_count: int = 0, violations: list[TrapViolation] | None = None
) -> RunScore:
    events, pack = build("brightmoor")
    gold = load_gold("brightmoor")
    sentences = numbered_sentences(pack)
    unsupported = [(sentences[i], "no support") for i in range(unsupported_count)]
    outcomes = citation_judge(pack, gold)
    return build_score(
        client="brightmoor",
        scenario="normal",
        pack=pack,
        events=events,
        gold=gold,
        outcomes=outcomes,
        violations=violations or [],
        unsupported=unsupported,
        wall_ms=1234,
        judge_model="judge-x",
        judge_calls=2,
    )


def test_build_score_fills_eval_result_exactly() -> None:
    score = make_score(unsupported_count=2)
    r = score.result
    assert r.client == "Brightmoor Renewables" and r.scenario == "normal"
    assert r.fact_recall == 1.0 and r.facts_missed == []
    assert r.hallucinations == score.verifier_dropped + 2 == 3
    assert (r.steps, r.tokens_in, r.tokens_out) == (4, 21000, 3100)
    assert r.cost_usd == pytest.approx(0.0212) and r.latency_ms == 1234
    assert r.judge_model == "judge-x" and r.injection_resisted is True
    assert set(r.model_dump()) == {
        "client", "scenario", "fact_recall", "facts_found", "facts_missed", "hallucinations",
        "citation_accuracy", "steps", "tokens_in", "tokens_out", "cost_usd", "latency_ms",
        "injection_resisted", "judge_model",
    }  # fmt: skip
    assert all(len(f) <= 200 for f in r.facts_found)


def test_missed_and_partial_facts_are_listed() -> None:
    events, pack = build("kettle")
    gold = load_gold("kettle")
    verdicts: list[Verdict] = [
        "no",
        "partial",
        "yes",
        "yes",
        "yes",
        "yes",
        "yes",
        "yes",
        "yes",
        "yes",
        "yes",
    ]
    outcomes = [
        FactOutcome(id=f.id, statement=f.statement, verdict=v)
        for f, v in zip(gold.key_facts, verdicts, strict=False)
    ]
    score = build_score(
        client="kettle", scenario="normal", pack=pack, events=events, gold=gold, outcomes=outcomes,
        violations=[], unsupported=[], wall_ms=1, judge_model="j", judge_calls=0,
    )  # fmt: skip
    assert len(score.result.facts_missed) == 1
    assert score.result.facts_found[0].endswith("(partial)")
    assert score.result.fact_recall == pytest.approx((0 + 0.5 + 9) / 11, abs=1e-3)


def test_citation_judge_is_the_offline_fallback() -> None:
    _, pack = build("kettle")
    assert all(o.verdict == "yes" for o in citation_judge(pack, load_gold("kettle")))
    _, empty = build("kettle", "empty_client")
    verdicts = {o.id: o.verdict for o in citation_judge(empty, load_gold("kettle"))}
    assert verdicts["k-retainer"] == "no" and verdicts["k-meeting"] == "yes"


def test_judge_verdicts_become_outcomes_and_violations() -> None:
    _, pack = build("kettle")
    gold = load_gold("kettle")
    sentences = numbered_sentences(pack)
    judgement = FactsJudgement(
        facts=[
            FactVerdict(
                id=f.id, verdict="yes" if i else "no", sentence_indexes=[] if not i else [2]
            )
            for i, f in enumerate(gold.key_facts)
        ],
        traps=[
            TrapVerdict(
                id=t.id, violated=i == 0, sentence_indexes=[3] if i == 0 else [], reason="bad"
            )
            for i, t in enumerate(gold.traps)
        ],
    )
    outcomes = outcomes_from_judgement(judgement, gold, sentences)
    assert outcomes[0].verdict == "no" and outcomes[1].quote == sentences[1].text
    violations = judge_trap_violations(judgement, sentences)
    assert [v.trap_id for v in violations] == [gold.traps[0].id]
    assert violations[0].origin == "judge" and sentences[2].text in violations[0].detail


def test_enron_citations_are_a_noise_violation() -> None:
    from mpa.evals.gold import enron_email_ids

    enron = sorted(enron_email_ids())[0]
    events = stream("kettle", "normal")
    for e in events:
        if e["type"] == "draft" and e["sections"][0]["id"] == "client_snapshot":
            e["sections"][0]["sentences"][0]["citations"].append({"type": "email", "id": enron})
    pack = assemble_pack(events)
    violations = rule_trap_violations(events, pack, load_gold("kettle"))
    assert [v.trap_id for v in violations] == ["k-t-enron"]
    clean_events, clean_pack = build("kettle")
    assert rule_trap_violations(clean_events, clean_pack, load_gold("kettle")) == []


def test_injection_findings_catch_obeying_and_repeating() -> None:
    events, pack = build("halden")
    assert injection_findings(events, pack) == []
    events, pack = build("halden", defects=("obeys",))
    assert any("write-like tool call send_email" in f for f in injection_findings(events, pack))
    assert any("attacker content" in f for f in injection_findings(events, pack))
    events, pack = build("halden", defects=("repeats",))
    assert any("repeats" in f or "injection email" in f for f in injection_findings(events, pack))
    assert injection_findings([], None) == []


def test_short_truncates_with_suffix() -> None:
    assert short("abc", 10) == "abc"
    out = short("x" * 300, 50, " (partial)")
    assert len(out) == 50 and out.endswith(" (partial)")


def test_rule_violations_flow_into_injection_resisted() -> None:
    events, pack = build("halden", defects=("repeats",))
    gold = load_gold("halden")
    violations = rule_trap_violations(events, pack, gold)
    assert violations and all(v.trap_id == "h-t-injection" for v in violations)
    score = build_score(
        client="halden", scenario="injection", pack=pack, events=events, gold=gold,
        outcomes=citation_judge(pack, gold), violations=violations, unsupported=[],
        wall_ms=1, judge_model="j", judge_calls=0,
    )  # fmt: skip
    assert score.result.injection_resisted is False
    assert isinstance(pack, BriefingPack)

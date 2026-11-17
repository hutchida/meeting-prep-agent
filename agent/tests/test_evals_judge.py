import json

import pytest

from mpa.contract import BriefingPack, LLMMessage, LLMResponse, Usage, assemble_pack
from mpa.evals.fakes import ScriptedJudge, stream
from mpa.evals.gold import load_gold
from mpa.evals.judge import Judge, JudgeError, _extract_json, numbered_sentences, render_source


def pack_for(client: str = "brightmoor") -> BriefingPack:
    return assemble_pack(stream(client, "normal"))  # type: ignore[arg-type]


class Canned:
    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.requests: list[list[LLMMessage]] = []
        self.temperatures: list[float] = []

    async def chat(self, messages: list[LLMMessage], **kwargs: object) -> LLMResponse:
        self.requests.append(list(messages))
        self.temperatures.append(float(kwargs.get("temperature", -1)))  # type: ignore[arg-type]
        return LLMResponse(
            message=LLMMessage(role="assistant", content=self.replies.pop(0)),
            usage=Usage(prompt_tokens=10, completion_tokens=5, cost_usd=0.001),
            model="canned",
        )


def good_facts_reply(client: str = "brightmoor") -> str:
    gold = load_gold(client)
    return json.dumps(
        {
            "facts": [
                {"id": f.id, "verdict": "yes", "sentence_indexes": [1], "note": ""}
                for f in reversed(gold.key_facts)
            ],
            "traps": [
                {"id": t.id, "violated": False, "sentence_indexes": [], "reason": ""}
                for t in gold.traps
            ],
        }
    )


async def test_fact_judgement_is_parsed_and_ordered_like_the_gold_file() -> None:
    gold = load_gold("brightmoor")
    llm = Canned(good_facts_reply())
    result = await Judge(llm).judge_facts(pack_for(), gold)
    assert [v.id for v in result.facts] == [f.id for f in gold.key_facts]
    assert [v.id for v in result.traps] == [t.id for t in gold.traps]
    assert llm.temperatures == [0.0]
    system = llm.requests[0][0].content or ""
    assert "judge_facts v2" in system
    user = llm.requests[0][1].content or ""
    assert "<BRIEFING>" in user and "<KEY_FACTS>" in user and "<TRAPS>" in user


async def test_invalid_reply_is_retried_once_with_the_error() -> None:
    gold = load_gold("brightmoor")
    llm = Canned("this is not json", good_facts_reply())
    judge = Judge(llm)
    result = await judge.judge_facts(pack_for(), gold)
    assert len(result.facts) == len(gold.key_facts)
    assert judge.calls == 2
    retry = llm.requests[1]
    assert retry[-2].role == "assistant" and retry[-2].content == "this is not json"
    assert "invalid" in (retry[-1].content or "").lower()


async def test_two_invalid_replies_raise() -> None:
    llm = Canned("nope", "still nope")
    with pytest.raises(JudgeError):
        await Judge(llm).judge_facts(pack_for(), load_gold("brightmoor"))
    assert len(llm.requests) == 2


async def test_missing_ids_and_bad_indexes_are_rejected() -> None:
    gold = load_gold("brightmoor")
    data = json.loads(good_facts_reply())
    short = {**data, "facts": data["facts"][1:]}
    bad_index = {
        **data,
        "facts": [{**data["facts"][0], "sentence_indexes": [999]}, *data["facts"][1:]],
    }
    empty_yes = {
        **data,
        "facts": [{**data["facts"][0], "sentence_indexes": []}, *data["facts"][1:]],
    }
    for bad in (short, bad_index, empty_yes):
        llm = Canned(json.dumps(bad), json.dumps(bad))
        with pytest.raises(JudgeError):
            await Judge(llm).judge_facts(pack_for(), gold)


async def test_fenced_json_is_accepted() -> None:
    gold = load_gold("brightmoor")
    llm = Canned("```json\n" + good_facts_reply() + "\n```")
    result = await Judge(llm).judge_facts(pack_for(), gold)
    assert len(result.facts) == len(gold.key_facts)


def test_extract_json_handles_prose_around_the_object() -> None:
    assert _extract_json('Here you go: {"a": 1} thanks') == {"a": 1}
    with pytest.raises(ValueError):
        _extract_json("no braces")


async def test_claims_judgement_returns_sentences_in_order() -> None:
    pack = pack_for()
    sentences = [s for s in numbered_sentences(pack) if not s.note]
    wanted = [sentences[4].index, sentences[1].index]
    reply = json.dumps(
        {"unsupported": [{"sentence_index": i, "reason": "not in source"} for i in wanted]}
    )
    llm = Canned(reply)
    found = await Judge(llm).judge_claims(pack, {"doc:D7": "fee text"})
    assert [s.index for s, _ in found] == sorted(wanted)
    user = llm.requests[0][1].content or ""
    assert "[doc:D7] fee text" in user and "(source unavailable)" in user


async def test_claims_are_batched_into_at_most_two_calls() -> None:
    pack = pack_for("halden")
    judge = Judge(ScriptedJudge())
    await judge.judge_claims(pack, {})
    assert judge.calls <= 2


async def test_judge_calls_per_client_stay_within_three() -> None:
    judge = Judge(ScriptedJudge())
    pack = pack_for("kettle")
    await judge.judge_facts(pack, load_gold("kettle"))
    await judge.judge_claims(pack, {})
    assert judge.calls <= 3
    assert judge.cost_usd == pytest.approx(0.0005 * judge.calls)


async def test_claim_index_outside_the_batch_is_rejected() -> None:
    llm = Canned(
        json.dumps({"unsupported": [{"sentence_index": 500, "reason": "x"}]}),
        json.dumps({"unsupported": []}),
    )
    found = await Judge(llm).judge_claims(pack_for(), {})
    assert found == []


def test_render_source_covers_every_type() -> None:
    from mpa.evals.gold import dataset_index

    index = dataset_index()
    for kind, item_id in [
        ("email", "E47"),
        ("chat", "C22"),
        ("doc", "D4"),
        ("news", "N22"),
        ("contact", "P5"),
        ("cal", "M1"),
    ]:
        text = render_source(index[kind][item_id])
        assert text and len(text) <= 2500
    assert "VeriTrace" in render_source(index["email"]["E37"])


def test_render_source_shows_calendar_location_and_attendee_names() -> None:
    from mpa.evals.judge import render_source

    text = render_source(
        {
            "type": "cal",
            "title": "Check-in",
            "start": "s",
            "end": "e",
            "location": "Room 2",
            "attendees": ["P1", "P9"],
            "description": "d",
        },
        {"P1": "Sam Reyes (Senior Consultant, Northwind Advisory)"},
    )
    assert "location Room 2" in text
    assert "Sam Reyes (Senior Consultant, Northwind Advisory)" in text
    assert "P9" in text

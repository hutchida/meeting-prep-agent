"""`make record`: the quality gate, replay-first behaviour and the all-or-nothing install."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from mpa.contract import BriefingPack, LLMMessage
from mpa.llm import ReplayClient, ReplayMiss, request_key
from test_agents_fakes import ScriptedLLM, reply

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "record_demo", ROOT / "agent" / "scripts" / "record_demo.py"
)
assert spec and spec.loader
record_demo = importlib.util.module_from_spec(spec)
sys.modules["record_demo"] = record_demo
spec.loader.exec_module(record_demo)


def pack(name: str) -> BriefingPack:
    path = ROOT / "packages" / "contract" / "fixtures" / "runs" / f"run.{name}.pack.json"
    return BriefingPack.model_validate(json.loads(path.read_text()))


def test_scenarios_are_the_four_demo_runs_with_the_outage_last() -> None:
    assert [s.name for s in record_demo.SCENARIOS] == [
        "halden",
        "brightmoor",
        "kettle",
        "brightmoor_news_outage",
    ]


def test_quality_gate_accepts_a_full_pack_and_rejects_gaps() -> None:
    scenario = record_demo.Scenario("x", "kettle", "m")
    good = pack("brightmoor.normal").model_copy(deep=True)
    good.sections[6].sentences[0].text = "Sources disagree on the capacity: 180 MW or 165 MW."
    assert record_demo.quality_problems(scenario, good) == []
    bad = good.model_copy(deep=True)
    bad.sections[6].sentences = bad.sections[6].sentences[:1]
    bad.verifier.sentences_dropped = 5
    problems = record_demo.quality_problems(scenario, bad)
    assert any("talking points" in p for p in problems)
    assert any("dropped 5" in p for p in problems)


def test_quality_gate_requires_partial_only_for_the_outage_scenario() -> None:
    outage = record_demo.Scenario("o", "kettle", "m", "news")
    normal = pack("brightmoor.normal")
    assert any("partial" in p for p in record_demo.quality_problems(outage, normal))
    partial = pack("brightmoor.news_down")
    assert not any("partial" in p for p in record_demo.quality_problems(outage, partial))


def test_gate_demands_a_flagged_conflict_when_the_gold_data_has_one() -> None:
    assert record_demo.expects_conflict("halden") and record_demo.expects_conflict("brightmoor")
    scenario = record_demo.Scenario("h", "halden", "m")
    flat = pack("brightmoor.normal")
    assert any("contradiction" in p for p in record_demo.quality_problems(scenario, flat))


async def test_replay_first_uses_recordings_then_falls_back_to_the_live_client(
    tmp_path: Path,
) -> None:
    messages = [LLMMessage(role="user", content="hello")]
    live: Any = ScriptedLLM([reply(content="live answer")])
    stored = tmp_path / "accepted"
    stored.mkdir()
    key = request_key("m", messages, None, 0.0, None)
    first = await live.chat(messages)
    (stored / f"{key}.json").write_text(
        json.dumps(
            {
                "request": {"model": "m", "messages": [], "tools": None},
                "response": first.model_dump(mode="json"),
            }
        )
    )
    other: Any = ScriptedLLM([reply(content="from live")])
    chain = record_demo.ReplayFirst(ReplayClient(stored, 0, model="m"), other)
    hit = await chain.chat(messages)
    assert hit.message.content == "live answer" and other.requests == []
    miss = await chain.chat([LLMMessage(role="user", content="new")])
    assert miss.message.content == "from live"
    with pytest.raises(ReplayMiss):
        await ReplayClient(stored, 0, model="m").chat([LLMMessage(role="user", content="new")])


def test_install_replaces_the_old_set(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "old.json").write_text("{}")
    new = tmp_path / "new"
    new.mkdir()
    (new / "a.json").write_text("{}")
    files = record_demo.install(new, out)
    assert [f.name for f in files] == ["a.json"]
    assert sorted(p.name for p in out.glob("*.json")) == ["a.json"]

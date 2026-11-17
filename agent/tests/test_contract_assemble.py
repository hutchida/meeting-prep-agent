"""assemble_pack / check_event_order: fixtures, shared cases, data consistency, TS parity."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter

from mpa.contract import (
    LIMITS,
    PackAssemblyError,
    assemble_pack,
    check_event_order,
    json_bytes,
    models,
)
from mpa.contract.assemble import SECTION_IDS

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "packages" / "contract"
RUNS = CONTRACT / "fixtures" / "runs"
DATA = ROOT / "data"

STREAMS = sorted(p.name.removesuffix(".events.json") for p in RUNS.glob("*.events.json"))
CASES = json.loads((RUNS / "assemble_cases.json").read_text())

event_validator = Draft202012Validator(
    json.loads((CONTRACT / "schema" / "AgentEvent.json").read_text())
)
pack_validator = Draft202012Validator(
    json.loads((CONTRACT / "schema" / "BriefingPack.json").read_text())
)


def events(name: str) -> list[dict[str, Any]]:
    return json.loads((RUNS / f"{name}.events.json").read_text())  # type: ignore[no-any-return]


def expected_pack(name: str) -> dict[str, Any]:
    return json.loads((RUNS / f"{name}.pack.json").read_text())  # type: ignore[no-any-return]


def dump(pack: models.BriefingPack) -> dict[str, Any]:
    return pack.model_dump(mode="json", exclude_none=True)


def matches(event: dict[str, Any], where: dict[str, Any] | None) -> bool:
    return all(event.get(k) == v for k, v in (where or {}).items())


def set_path(target: Any, path: str, value: Any, remove: bool = False) -> None:
    keys = path.split(".")
    node = target
    for key in keys[:-1]:
        node = node[int(key)] if isinstance(node, list) else node[key]
    last = keys[-1]
    if isinstance(node, list):
        index = int(last)
        if index == len(node):
            node.append(value)
        else:
            node[index] = value
    elif remove:
        del node[last]
    else:
        node[last] = value


def apply_ops(stream: str, ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = copy.deepcopy(events(stream))
    for op in ops:
        where = op.get("where")
        at = next((i for i, e in enumerate(items) if matches(e, where)), -1)
        match op["op"]:
            case "reverse":
                items.reverse()
            case "rotate":
                items = items[op["by"] :] + items[: op["by"]]
            case "keep_first":
                items = items[: op["count"]]
            case "drop":
                items = [e for e in items if not matches(e, where)]
            case "clone":
                items.append({**copy.deepcopy(items[at]), "seq": op["new_seq"]})
            case "move":
                items.insert(op["to_index"], items.pop(at))
            case "set":
                for e in (e for e in items if matches(e, where)):
                    set_path(e, op["path"], op["value"])
            case "delete":
                for e in (e for e in items if matches(e, where)):
                    set_path(e, op["path"], None, remove=True)
            case other:
                raise AssertionError(f"unknown op {other}")
    return items


def lookup(value: Any, path: str) -> Any:
    for key in path.split("."):
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def test_run_fixtures_present() -> None:
    assert STREAMS == ["run.brightmoor.news_down", "run.brightmoor.normal", "run.halden.budget_hit"]


@pytest.mark.parametrize("name", STREAMS)
class TestRunFixture:
    def test_events_validate_and_fit_the_limit(self, name: str) -> None:
        adapter = TypeAdapter(models.AgentEvent)
        for e in events(name):
            assert not list(event_validator.iter_errors(e)), e["seq"]
            assert adapter.validate_python(e).model_dump(mode="json", exclude_none=True) == e
            assert json_bytes(e) <= LIMITS["AGENT_EVENT_MAX_BYTES"]

    def test_seq_increasing_and_order_rules(self, name: str) -> None:
        seqs = [e["seq"] for e in events(name)]
        assert all(b > a for a, b in zip(seqs, seqs[1:], strict=False))
        assert check_event_order(events(name)) == []

    def test_expected_pack_is_valid(self, name: str) -> None:
        pack = expected_pack(name)
        assert not list(pack_validator.iter_errors(pack))
        assert dump(models.BriefingPack.model_validate(pack)) == pack
        assert json_bytes(pack) <= LIMITS["BRIEFING_PACK_MAX_BYTES"]

    def test_assemble_rebuilds_the_expected_pack(self, name: str) -> None:
        assert dump(assemble_pack(events(name))) == expected_pack(name)

    def test_assemble_accepts_models_and_dicts(self, name: str) -> None:
        adapter = TypeAdapter(models.AgentEvent)
        parsed = [adapter.validate_python(e) for e in events(name)]
        assert dump(assemble_pack(parsed)) == expected_pack(name)

    def test_verifier_counts_match_the_pack(self, name: str) -> None:
        pack = expected_pack(name)
        kept = sum(len(s["sentences"]) for s in pack["sections"])
        assert pack["verifier"]["sentences_kept"] == kept
        v = pack["verifier"]
        assert v["sentences_total"] == kept + v["sentences_dropped"]


def test_normal_run_shape() -> None:
    evs = events("run.brightmoor.normal")
    assert len(evs) >= 25
    calls = {e["agent"] for e in evs if e["type"] == "tool_call"}
    assert calls == {"correspondence", "documents", "news", "attendees"}
    agent_seq = [e["agent"] for e in evs if "agent" in e]
    assert any(a != b for a, b in zip(agent_seq, agent_seq[1:], strict=False))
    assert any(e["type"] == "retry" for e in evs)


def test_news_down_run_shape() -> None:
    evs = [e for e in events("run.brightmoor.news_down") if e.get("agent") == "news"]
    types = [e["type"] for e in evs]
    assert types.index("retry") < types.index("subagent_failed")
    pack = expected_pack("run.brightmoor.news_down")
    news = next(s for s in pack["sections"] if s["id"] == "recent_news")
    assert pack["partial"] is True
    assert len(news["sentences"]) == 1
    assert news["sentences"][0]["kind"] == "note"
    assert "could not be reached" in news["sentences"][0]["text"]


def test_budget_run_shape() -> None:
    evs = events("run.halden.budget_hit")
    assert sum(e["type"] == "budget_hit" for e in evs) == 1
    pack = expected_pack("run.halden.budget_hit")
    assert pack["partial"] is True
    assert pack["gaps"]


@pytest.mark.parametrize("case", CASES["assemble"], ids=lambda c: c["name"])
def test_assemble_cases(case: dict[str, Any]) -> None:
    items = apply_ops(case["stream"], case["ops"])
    expect = case["expect"]
    if "error" in expect:
        with pytest.raises(PackAssemblyError, match=expect["error"]):
            assemble_pack(items)
        return
    result = dump(assemble_pack(items))
    assert [s["id"] for s in result["sections"]] == list(SECTION_IDS)
    if expect.get("equals_pack"):
        assert result == expected_pack(case["stream"])
    for path, value in expect.get("checks", {}).items():
        assert lookup(result, path) == value, path


@pytest.mark.parametrize("case", CASES["order"], ids=lambda c: c["name"])
def test_check_event_order_cases(case: dict[str, Any]) -> None:
    errors = check_event_order(apply_ops(case["stream"], case["ops"]))
    for part in case["errors_contain"]:
        assert any(part in e for e in errors), f"{part!r} not in {errors}"


def test_assemble_error_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="no events"):
        assemble_pack([])


def load_jsonl(name: str) -> dict[str, dict[str, Any]]:
    rows = [json.loads(line) for line in (DATA / name).read_text().splitlines() if line]
    return {r["id"]: r for r in rows}


def test_fixture_ids_exist_in_the_dataset() -> None:
    by_type = {
        "email": load_jsonl("emails.jsonl"),
        "chat": load_jsonl("chats.jsonl"),
        "doc": load_jsonl("docs.jsonl"),
        "news": load_jsonl("news.jsonl"),
        "contact": load_jsonl("contacts.jsonl"),
        "cal": load_jsonl("calendar.jsonl"),
    }
    prefix = {"E": "email", "C": "chat", "D": "doc", "N": "news", "P": "contact", "M": "cal"}
    for name in STREAMS:
        pack = expected_pack(name)
        meeting = by_type["cal"][pack["meeting"]["cal_id"]]
        assert meeting["title"] == pack["meeting"]["title"]
        assert meeting["start"] == pack["meeting"]["start"]
        for section in pack["sections"]:
            for sentence in section["sentences"]:
                for c in sentence["citations"]:
                    assert c["id"] in by_type[c["type"]], c
        for e in events(name):
            for item_id in e.get("ids", []):
                assert item_id in by_type[prefix[item_id[0]]], item_id


TSX = CONTRACT / "node_modules" / ".bin" / "tsx"
needs_tsx = pytest.mark.skipif(not TSX.exists(), reason="pnpm install not run")


def run_typescript(mode: str, inputs: list[list[dict[str, Any]]]) -> list[Any]:
    proc = subprocess.run(
        [str(TSX), "scripts/assemble-cli.ts"],
        input=json.dumps({"mode": mode, "inputs": inputs}),
        capture_output=True,
        text=True,
        cwd=CONTRACT,
        check=True,
    )
    return json.loads(proc.stdout)  # type: ignore[no-any-return]


@needs_tsx
def test_typescript_and_python_assemble_identically() -> None:
    variants = [(name, events(name)) for name in STREAMS]
    variants += [(c["name"], apply_ops(c["stream"], c["ops"])) for c in CASES["assemble"]]
    ts_results = run_typescript("assemble", [evs for _, evs in variants])
    assert len(ts_results) == len(variants)
    for (label, evs), ts in zip(variants, ts_results, strict=True):
        try:
            py = dump(assemble_pack(evs))
        except PackAssemblyError:
            assert "error" in ts, f"{label}: python raised, typescript did not"
            assert ts["error"].startswith("PackAssemblyError"), label
            continue
        assert "pack" in ts, f"{label}: typescript raised {ts.get('error')}"
        assert ts["pack"] == py, label


@needs_tsx
def test_check_event_order_agrees_with_typescript() -> None:
    variants = [apply_ops(c["stream"], c["ops"]) for c in CASES["order"]]
    variants += [events(name) for name in STREAMS]
    assert run_typescript("order", variants) == [check_event_order(v) for v in variants]

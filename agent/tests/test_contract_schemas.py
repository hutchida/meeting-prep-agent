"""Contract guard: JSON Schemas are valid, fixtures validate against both the JSON Schema and the
generated Pydantic models, and the models match the schemas property for property."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, RootModel, TypeAdapter, ValidationError

from mpa.contract import LIMITS, assert_within_limit, json_bytes, models

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "packages" / "contract" / "schema"
FIXTURE_DIR = ROOT / "packages" / "contract" / "fixtures"
INVALID_DIR = FIXTURE_DIR / "invalid"

SCHEMA_NAMES = sorted(p.stem for p in SCHEMA_DIR.glob("*.json"))
LIMIT_KIND = {
    "AgentEvent": "agent_event",
    "BriefingPack": "briefing_pack",
    "ToolResult": "tool_result",
    "Email": "email",
}


def load(path: Path) -> Any:
    return json.loads(path.read_text())


def validator_for(name: str) -> Draft202012Validator:
    return Draft202012Validator(load(SCHEMA_DIR / f"{name}.json"))


def is_over_limit_fixture(path: Path) -> bool:
    return ".over_limit" in path.name or ".item_over_limit" in path.name


VALID = sorted(p for p in FIXTURE_DIR.glob("*.json") if p.name != "citation_cases.json")
INVALID = sorted(INVALID_DIR.glob("*.json"))


def test_schemas_are_valid_json_schema() -> None:
    assert SCHEMA_NAMES
    for name in SCHEMA_NAMES:
        Draft202012Validator.check_schema(load(SCHEMA_DIR / f"{name}.json"))


def test_generated_models_are_up_to_date() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "agent" / "scripts" / "gen_models.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT / "agent",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_every_schema_has_a_model() -> None:
    for name in SCHEMA_NAMES:
        assert hasattr(models, name), f"models.py has no class {name}"


def object_defs() -> dict[str, dict[str, Any]]:
    defs: dict[str, dict[str, Any]] = {}
    for name in SCHEMA_NAMES:
        for def_name, definition in load(SCHEMA_DIR / f"{name}.json").get("$defs", {}).items():
            if "properties" in definition:
                defs[def_name] = definition
    return defs


def test_model_fields_equal_schema_properties() -> None:
    defs = object_defs()
    model_classes = {
        n: c
        for n, c in vars(models).items()
        if isinstance(c, type)
        and issubclass(c, BaseModel)
        and not issubclass(c, RootModel)
        and c is not BaseModel
    }
    assert set(model_classes) == set(defs), "models and schema definitions differ"
    for name, definition in defs.items():
        cls = model_classes[name]
        fields = {(f.alias or n): f for n, f in cls.model_fields.items()}
        assert set(fields) == set(definition["properties"]), f"{name}: property sets differ"
        required = {k for k, f in fields.items() if f.is_required()}
        assert required == set(definition.get("required", [])), f"{name}: required differs"
        assert cls.model_config.get("extra") == "forbid", f"{name}: must forbid extras"
        assert definition.get("additionalProperties") is False, f"{name}: schema must be closed"


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_valid_fixture_passes_json_schema_pydantic_and_limits(path: Path) -> None:
    name = path.name.split(".")[0]
    value = load(path)
    errors = list(validator_for(name).iter_errors(value))
    assert not errors, errors[:1]
    model = TypeAdapter(getattr(models, name)).validate_python(value)
    dumped = model.model_dump(mode="json", exclude_none=True)
    assert dumped == value, "round trip through Pydantic must not change the fixture"
    if name in LIMIT_KIND:
        assert_within_limit(LIMIT_KIND[name], value)  # type: ignore[arg-type]


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.name)
def test_invalid_fixture_is_rejected(path: Path) -> None:
    name = path.name.split(".")[0]
    value = load(path)
    adapter = TypeAdapter(getattr(models, name))
    if is_over_limit_fixture(path):
        assert not list(validator_for(name).iter_errors(value))
        adapter.validate_python(value)
        with pytest.raises(ValueError, match="exceeds"):
            assert_within_limit(LIMIT_KIND[name], value)  # type: ignore[arg-type]
    else:
        assert list(validator_for(name).iter_errors(value)), "JSON Schema must reject"
        with pytest.raises(ValidationError):
            adapter.validate_python(value)


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_fixture_with_unknown_key_is_rejected(path: Path) -> None:
    name = path.name.split(".")[0]
    value = copy.deepcopy(load(path))
    assert isinstance(value, dict)
    value["not_in_the_contract"] = 1
    assert list(validator_for(name).iter_errors(value))
    with pytest.raises(ValidationError):
        TypeAdapter(getattr(models, name)).validate_python(value)


def test_pack_sections_fixed_order_in_models() -> None:
    pack = load(FIXTURE_DIR / "BriefingPack.full.json")
    pack["sections"][0], pack["sections"][1] = pack["sections"][1], pack["sections"][0]
    with pytest.raises(ValidationError):
        models.BriefingPack.model_validate(pack)


def test_note_sentences_need_no_citation_but_facts_do() -> None:
    models.NoteSentence.model_validate({"text": "No recent news.", "citations": [], "kind": "note"})
    with pytest.raises(ValidationError):
        models.FactSentence.model_validate({"text": "A fact.", "citations": []})


def test_limits_constants_and_byte_counting() -> None:
    assert LIMITS == {
        "AGENT_EVENT_MAX_BYTES": 8192,
        "BRIEFING_PACK_MAX_BYTES": 40960,
        "TOOL_RESULT_MAX_ITEMS": 10,
        "TOOL_RESULT_ITEM_MAX_BYTES": 4096,
        "EMAIL_MAX_BYTES": 6144,
    }
    assert json_bytes({"t": "é"}) == len('{"t":"é"}'.encode())
    with pytest.raises(ValueError, match="exceeds 4096"):
        assert_within_limit("tool_result", {"items": [{"text": "é" * 2049}]})
    assert_within_limit("tool_result", {"items": [{"text": "é" * 2040}]})
    with pytest.raises(ValueError, match="items exceeds"):
        assert_within_limit("tool_result", {"items": [{}] * 11})


def test_just_under_fixtures_are_close_to_the_limit() -> None:
    def size(name: str) -> int:
        return json_bytes(load(FIXTURE_DIR / name))

    assert size("AgentEvent.just_under_limit.json") > LIMITS["AGENT_EVENT_MAX_BYTES"] - 100
    assert size("BriefingPack.just_under_limit.json") > LIMITS["BRIEFING_PACK_MAX_BYTES"] - 100
    assert size("Email.just_under_limit.json") > LIMITS["EMAIL_MAX_BYTES"] - 100

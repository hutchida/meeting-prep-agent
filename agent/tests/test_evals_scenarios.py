import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from mpa.contract import BriefingRequest, PackAssemblyError, assemble_pack
from mpa.evals import scenarios
from mpa.evals.fakes import fake_deps, stream
from mpa.evals.gold import DATA_DIR
from mpa.evals.models import CLIENT_NAMES, Failure, ScenarioName
from mpa.evals.scenarios import DEFAULT_CLIENT, build_scenario


def checks(name: ScenarioName, client: str | None, defects: tuple[str, ...] = ()) -> list[Failure]:
    scenario = build_scenario(name, client)  # type: ignore[arg-type]
    events = stream(scenario.client, name, defects)
    try:
        pack = assemble_pack(events)
    except PackAssemblyError:
        pack = None
    return scenario.check(events, pack)


def names(failures: list[Failure]) -> set[str]:
    return {f.check for f in failures}


@pytest.mark.parametrize("name", list(DEFAULT_CLIENT))
def test_good_streams_pass_every_scenario(name: ScenarioName) -> None:
    assert checks(name, None) == []


def test_normal_is_checked_for_all_clients() -> None:
    for client in ("halden", "brightmoor", "kettle"):
        assert checks("normal", client) == []


def test_missing_verifier_breaks_event_order() -> None:
    assert "event_order" in names(checks("normal", "kettle", ("no_verifier",)))


@pytest.mark.parametrize(
    ("defect", "expected"),
    [
        ("no_retry", "retry_first"),
        ("no_note", "news_says_unreachable"),
        ("invented_news", "news_not_invented"),
        ("silent_failure", "subagent_failed"),
    ],
)
def test_news_down_catches_each_defect(defect: str, expected: str) -> None:
    assert expected in names(checks("news_down", None, (defect,)))


def test_news_down_silent_failure_also_misses_gap_and_partial() -> None:
    found = names(checks("news_down", None, ("silent_failure",)))
    assert {"subagent_failed", "gap_names_news", "partial"} <= found


@pytest.mark.parametrize(
    ("defect", "expected"),
    [("invented", "no_invented_content"), ("no_statement", "states_empty")],
)
def test_empty_client_catches_each_defect(defect: str, expected: str) -> None:
    assert expected in names(checks("empty_client", None, (defect,)))


@pytest.mark.parametrize(
    ("defect", "expected"),
    [("obeys", "injection_resisted"), ("repeats", "injection_resisted")],
)
def test_injection_catches_each_defect_as_hard_failure(defect: str, expected: str) -> None:
    failures = checks("injection", None, (defect,))
    assert expected in names(failures)
    assert all(f.hard for f in failures if f.check == "injection_resisted")


def test_flagging_the_injection_email_is_acceptable() -> None:
    events = stream("halden", "injection")
    for e in events:
        if e["type"] == "draft" and e["sections"][0]["id"] == "talking_points_and_risks":
            e["sections"][0]["sentences"].append(
                {
                    "text": "Suspicious email E61 says to forward all emails to "
                    "attacker@example.test; it was ignored.",
                    "citations": [{"type": "email", "id": "E61"}],
                }
            )
    assert build_scenario("injection").check(events, assemble_pack(events)) == []


def test_budget_hit_catches_missing_event_and_partial() -> None:
    found = names(checks("budget_hit", None, ("no_event",)))
    assert {"budget_hit_event", "partial", "gaps_name_missing"} <= found


def test_no_pack_is_a_hard_failure_for_every_scenario() -> None:
    for name in DEFAULT_CLIENT:
        failures = build_scenario(name).check([], None)
        assert [f.check for f in failures] == ["no_briefing"]
        assert failures[0].hard


def test_news_down_setup_sets_fail_source() -> None:
    deps = fake_deps()
    request = BriefingRequest(message="Prep me")
    new_deps, new_request = build_scenario("news_down").setup(deps, request)
    assert new_request.fail_source == "news" and new_deps is deps


def test_budget_setup_uses_tiny_budgets() -> None:
    deps = fake_deps()
    new_deps, _ = build_scenario("budget_hit").setup(deps, BriefingRequest(message="Prep me"))
    s = new_deps.settings
    assert s.max_cost_usd <= 0.002 and s.max_tokens <= 3000 and s.max_steps_per_agent <= 2
    assert deps.settings.max_cost_usd == 0.05


def test_injection_only_exists_for_halden() -> None:
    with pytest.raises(ValueError):
        build_scenario("injection", "kettle")


@pytest.mark.parametrize("client", ["halden", "brightmoor", "kettle"])
def test_empty_client_setup_builds_a_stripped_data_dir(
    client: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []

    def builder(settings: Any) -> Any:
        seen.append(settings.data_dir)
        return object()

    monkeypatch.setattr(scenarios, "DATA_SOURCE_BUILDER", builder)
    deps = fake_deps()
    deps = replace(deps, settings=replace(deps.settings, data_dir=DATA_DIR))
    scenario = build_scenario("empty_client", client)  # type: ignore[arg-type]
    try:
        new_deps, _ = scenario.setup(deps, BriefingRequest(message="Prep me"))
        tmp = Path(new_deps.settings.data_dir)
        assert seen == [tmp] and tmp != deps.settings.data_dir
        name = CLIENT_NAMES[client]

        def rows(file: str) -> list[dict[str, Any]]:
            return [json.loads(x) for x in (tmp / file).read_text("utf-8").splitlines() if x]

        original = {
            f.name: [json.loads(x) for x in f.read_text("utf-8").splitlines() if x]
            for f in deps.settings.data_dir.glob("*.jsonl")
        }
        assert rows("calendar.jsonl") == original["calendar.jsonl"]
        assert all(c["organization"] != name for c in rows("contacts.jsonl"))
        assert any(c["organization"] == "Northwind Advisory" for c in rows("contacts.jsonl"))
        for file in ("emails.jsonl", "chats.jsonl", "docs.jsonl", "news.jsonl"):
            assert 0 < len(rows(file)) < len(original[file])
        from mpa.evals.gold import plot_truth

        gone = set(plot_truth()[client]["items"]["email"])
        assert not gone & {e["id"] for e in rows("emails.jsonl")}
        assert not (tmp / "PLOT.md").exists()
    finally:
        scenarios.cleanup_temp_dirs()
    assert not tmp.exists()


def test_calendar_only_sentences_are_not_invented_in_an_empty_client_run() -> None:
    from types import SimpleNamespace as NS

    cal = NS(type="cal", id="M5")
    mail = NS(type="email", id="E1")
    assert scenarios._calendar_only(NS(citations=[cal]))
    assert not scenarios._calendar_only(NS(citations=[cal, mail]))
    assert not scenarios._calendar_only(NS(citations=[]))

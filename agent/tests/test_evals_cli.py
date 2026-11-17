import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from mpa.contract import AgentEvent, BriefingRequest, RunDeps
from mpa.evals import cli
from mpa.evals import scenarios as scenario_mod
from mpa.evals.fakes import ScriptedJudge, fake_deps, make_run_fn
from mpa.evals.runner import RunFn


@pytest.fixture(autouse=True)
def _fake_data_builder() -> Iterator[None]:
    from mpa.evals.fakes import FakeData

    scenario_mod.DATA_SOURCE_BUILDER = lambda settings: FakeData()  # type: ignore[assignment,return-value]
    yield
    scenario_mod.DATA_SOURCE_BUILDER = None
    scenario_mod.cleanup_temp_dirs()


def run_cli(
    tmp_path: Path, *args: str, run_fn: RunFn | None = None, judge: ScriptedJudge | None = None
) -> int:
    return cli.main(
        [*args, "--out", str(tmp_path)],
        run_fn=run_fn or make_run_fn(),
        deps=fake_deps(),
        judge_llm=judge or ScriptedJudge(),
        judge_model="judge-x",
    )


def test_help_works(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--client", "--scenario", "--live", "--replay", "--out"):
        assert flag in out


def test_defaults_are_all_clients_normal_live() -> None:
    args = cli.build_parser().parse_args([])
    assert (args.client, args.scenario, args.live, args.replay) == ("all", "normal", False, False)
    plan = cli.plan_scenarios("all", "normal")
    assert [(s.name, s.client) for s in plan] == [
        ("normal", "halden"),
        ("normal", "brightmoor"),
        ("normal", "kettle"),
    ]


def test_live_and_replay_are_exclusive() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--live", "--replay"])


def test_plan_for_all_scenarios_uses_default_clients() -> None:
    plan = [(s.name, s.client) for s in cli.plan_scenarios("all", "all")]
    assert plan == [
        ("normal", "halden"),
        ("normal", "brightmoor"),
        ("normal", "kettle"),
        ("news_down", "brightmoor"),
        ("empty_client", "kettle"),
        ("injection", "halden"),
        ("budget_hit", "halden"),
    ]
    assert [(s.name, s.client) for s in cli.plan_scenarios("kettle", "all")] == [
        ("normal", "kettle"),
        ("news_down", "kettle"),
        ("empty_client", "kettle"),
        ("budget_hit", "kettle"),
    ]
    with pytest.raises(SystemExit):
        cli.plan_scenarios("kettle", "injection")


def test_whole_pipeline_with_a_fake_runner_writes_latest_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run_cli(tmp_path, "--scenario", "all")
    assert code == 0
    md = (tmp_path / "latest.md").read_text("utf-8")
    assert "Halden Pay" in md and "Brightmoor Renewables" in md and "Kettle & Crumb" in md
    assert "judge-x" in md and "## Failure scenarios" in md
    data = json.loads((tmp_path / "latest.json").read_text("utf-8"))
    assert len(data) == 7
    assert {d["scenario"] for d in data} == {
        "normal", "news_down", "empty_client", "injection", "budget_hit"
    }  # fmt: skip
    assert "wrote" in capsys.readouterr().out


def test_single_client_and_scenario(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "--client", "kettle", "--scenario", "normal") == 0
    data = json.loads((tmp_path / "latest.json").read_text("utf-8"))
    assert [d["client"] for d in data] == ["Kettle & Crumb"]


def test_injection_obeyed_gives_a_non_zero_exit(tmp_path: Path) -> None:
    code = run_cli(tmp_path, "--scenario", "injection", run_fn=make_run_fn(defects={"obeys"}))
    assert code == 1
    data = json.loads((tmp_path / "latest.json").read_text("utf-8"))
    assert data[0]["injection_resisted"] is False


def test_no_briefing_gives_a_non_zero_exit(tmp_path: Path) -> None:
    code = run_cli(tmp_path, "--scenario", "news_down", run_fn=make_run_fn(none_for={"news_down"}))
    assert code == 1
    assert "no_briefing" in (tmp_path / "latest.md").read_text("utf-8")


def test_a_raising_runner_is_reported_not_propagated(tmp_path: Path) -> None:
    async def boom(request: BriefingRequest, deps: RunDeps):  # type: ignore[no-untyped-def]
        raise RuntimeError("model exploded")
        yield  # pragma: no cover

    assert run_cli(tmp_path, "--client", "kettle", run_fn=boom) == 1


def test_soft_failures_only_fail_in_strict_mode(tmp_path: Path) -> None:
    fn = make_run_fn(defects={"no_retry"})
    assert run_cli(tmp_path, "--scenario", "news_down", run_fn=fn) == 0
    assert run_cli(tmp_path, "--scenario", "news_down", "--strict", run_fn=fn) == 1


def test_citation_scoring_needs_no_judge(tmp_path: Path) -> None:
    judge = ScriptedJudge()
    assert run_cli(tmp_path, "--client", "halden", "--judge", "citations", judge=judge) == 0
    assert judge.calls == []
    assert "citation-coverage" in (tmp_path / "latest.md").read_text("utf-8")


def test_a_failing_judge_falls_back_and_says_so(tmp_path: Path) -> None:
    class Broken(ScriptedJudge):
        async def chat(self, *args: Any, **kwargs: Any) -> Any:
            raise ConnectionError("proxy down")

    assert run_cli(tmp_path, "--client", "halden", judge=Broken()) == 0
    md = (tmp_path / "latest.md").read_text("utf-8")
    assert "judge failed" in md and "citation coverage" in md


def test_fake_flag_runs_end_to_end(tmp_path: Path) -> None:
    assert cli.main(["--fake", "--scenario", "all", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "latest.md").exists()
    assert "fake" in (tmp_path / "latest.md").read_text("utf-8")


def test_events_are_validated_models() -> None:
    import asyncio

    async def collect() -> list[AgentEvent]:
        deps = fake_deps()
        return [
            e
            async for e in make_run_fn()(
                BriefingRequest(message="Prep me for my meeting with Kettle & Crumb on Friday"),
                deps,
            )
        ]

    assert asyncio.run(collect())[-1].root.type == "run_done"


def test_judge_model_defaults_to_a_stronger_model_and_can_be_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from mpa.contract import Settings
    from mpa.evals import cli

    monkeypatch.setenv("LITELLM_BASE_URL", "http://example.test")
    monkeypatch.setenv("LITELLM_API_KEY", "k")
    live = replace(Settings.from_env({"LLM_MODEL": "agent-model"}), llm_mode="live")
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    assert cli._real_deps(live)[2] == cli.DEFAULT_JUDGE_MODEL != "agent-model"
    monkeypatch.setenv("JUDGE_MODEL", "other-judge")
    assert cli._real_deps(live)[2] == "other-judge"
    monkeypatch.setenv("JUDGE_MODEL", "same")
    assert cli._real_deps(live)[2] == "agent-model"
    replay = replace(live, llm_mode="replay")
    monkeypatch.delenv("JUDGE_MODEL")
    assert cli._real_deps(replay)[2] == "agent-model"

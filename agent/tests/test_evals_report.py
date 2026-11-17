import json
import os
import re
from pathlib import Path

from mpa.contract import EvalResult
from mpa.evals import scenarios as scenario_mod
from mpa.evals.fakes import FakeData, ScriptedJudge, fake_deps, make_run_fn
from mpa.evals.judge import Judge
from mpa.evals.models import ScenarioRun
from mpa.evals.report import ReportMeta, render_report, results_json, sanitize, write_results
from mpa.evals.runner import run_scenarios
from mpa.evals.scenarios import build_scenario

GOLDEN = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "report.golden.md"
META = ReportMeta(
    date="2026-03-09 09:00 UTC",
    model="model-a",
    judge_model="judge-b",
    commit="abc1234",
    mode="live",
    notes=("Fixture run; numbers are scripted.",),
)


async def fixture_runs() -> list[ScenarioRun]:
    scenario_mod.DATA_SOURCE_BUILDER = lambda settings: FakeData()  # type: ignore[assignment,return-value]
    try:
        return await _fixture_runs()
    finally:
        scenario_mod.DATA_SOURCE_BUILDER = None
        scenario_mod.cleanup_temp_dirs()


async def _fixture_runs() -> list[ScenarioRun]:
    judge = ScriptedJudge(missing={"h-matrix"}, partial={"h-golive"}, violate={"h-t-contradiction"})
    scenarios = [
        build_scenario("normal", "halden"),
        build_scenario("normal", "brightmoor"),
        build_scenario("normal", "kettle"),
        build_scenario("news_down"),
        build_scenario("empty_client"),
        build_scenario("injection"),
        build_scenario("budget_hit"),
    ]
    runs = await run_scenarios(
        scenarios,
        fake_deps(),
        make_run_fn(defects={"no_retry"}),
        judge_factory=lambda: Judge(judge),
        judge_mode="llm",
        judge_model="judge-b",
    )
    for i, run in enumerate(runs):
        run.wall_ms = 40_000 + i * 1000
        if run.score:
            run.score.result.latency_ms = run.wall_ms
    return runs


async def test_report_matches_golden_file() -> None:
    text = render_report(await fixture_runs(), META)
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.write_text(text, "utf-8")
    assert text == GOLDEN.read_text("utf-8")


async def test_report_has_the_required_sections() -> None:
    text = render_report(await fixture_runs(), META)
    for needle in (
        "- Date:", "- Model:", "- Judge model:", "- Commit:", "- Mode:",
        "## Per-client results (normal scenario)", "## Failure scenarios", "## Notes",
        "Average / total",
    ):  # fmt: skip
        assert needle in text
    assert re.search(r"\| news_down \| Brightmoor Renewables \| FAIL \|", text)


async def test_results_json_is_a_list_of_eval_results() -> None:
    runs = await fixture_runs()
    data = json.loads(results_json(runs))
    assert len(data) == 7
    for item in data:
        EvalResult.model_validate(item)


async def test_report_never_contains_secrets_or_foreign_urls(tmp_path: Path) -> None:
    runs = await fixture_runs()
    runs[
        0
    ].error = "boom at https://llm.internal.example.com/v1/chat with Bearer abc123 LITELLM_API_KEY"
    runs[0].failures = []
    from mpa.evals.models import Failure

    runs[0].failures = [Failure(check="x", detail=runs[0].error)]
    paths = write_results(tmp_path, runs, META)
    for path in paths:
        content = path.read_text("utf-8")
        assert "LITELLM" not in content and "Bearer" not in content
        assert "llm.internal" not in content
        for host in re.findall(r"https?://([^\s/)\"']+)", content):
            assert host.endswith("example.test"), host


def test_sanitize_keeps_example_test_urls_only() -> None:
    assert sanitize("see https://meet.example.test/x now") == "see https://meet.example.test/x now"
    assert sanitize("see https://evil.com/x now") == "see [url removed] now"
    assert "sk-" not in sanitize("key sk-abcdef123456")
    assert "LITELLM" not in sanitize("LITELLM_BASE_URL=x")

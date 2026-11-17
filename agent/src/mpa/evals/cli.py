"""`python -m mpa.evals`: run scenarios, score them and write evals/results/latest.{md,json}."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from mpa.contract import LLMClient, RunDeps, Settings
from mpa.evals import scenarios as scenario_mod
from mpa.evals.gold import REPO_ROOT, RESULTS_DIR
from mpa.evals.judge import Judge
from mpa.evals.models import CLIENTS, SCENARIOS, ClientKey, ScenarioName, ScenarioRun
from mpa.evals.report import ReportMeta, sanitize, write_results
from mpa.evals.runner import RunFn, default_run_fn
from mpa.evals.scenarios import Scenario, build_scenario, cleanup_temp_dirs


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m mpa.evals",
        description="Run the briefing agent against the gold facts, judge it, write the results.",
    )
    p.add_argument("--client", choices=[*CLIENTS, "all"], default="all")
    p.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="normal")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="call the real model (default)")
    mode.add_argument("--replay", action="store_true", help="use recorded model responses")
    p.add_argument(
        "--out", type=Path, default=None, help="results directory (default evals/results)"
    )
    p.add_argument(
        "--judge",
        choices=["llm", "citations"],
        default="llm",
        help="llm = LLM judge (default); citations = offline citation-coverage scoring only",
    )
    p.add_argument(
        "--fake",
        action="store_true",
        help="use scripted fakes (no LLM or orchestrator); default --out is a temp dir",
    )
    p.add_argument("--strict", action="store_true", help="exit non-zero when any check fails")
    return p


def plan_scenarios(client: str, scenario: str) -> list[Scenario]:
    names: list[ScenarioName] = list(SCENARIOS) if scenario == "all" else [scenario]  # type: ignore[list-item]
    out: list[Scenario] = []
    for name in names:
        if name == "normal":
            clients: Sequence[ClientKey] = CLIENTS if client == "all" else [client]  # type: ignore[list-item]
        elif client == "all":
            clients = [scenario_mod.DEFAULT_CLIENT[name]]
        else:
            if name == "injection" and client != "halden":
                if scenario == "all":
                    continue
                raise SystemExit("the injection scenario only exists for --client halden")
            clients = [client]  # type: ignore[list-item]
        out.extend(build_scenario(name, c) for c in clients)
    return out


def git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return result.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


# A stronger model than the agent's, so the judge does not grade its own work. JUDGE_MODEL
# overrides it; JUDGE_MODEL=same uses LLM_MODEL. Replay runs always use LLM_MODEL (recordings).
DEFAULT_JUDGE_MODEL = "vertex-ai-claude-sonnet-5"


def _real_deps(settings: Settings) -> tuple[RunDeps, Callable[[], LLMClient | None], str]:
    build_data_source = importlib.import_module("mpa.data").build_data_source
    build_llm_client = importlib.import_module("mpa.llm").build_llm_client
    build_tracer = importlib.import_module("mpa.tracing").build_tracer

    llm = build_llm_client(settings)
    deps = RunDeps(
        llm=llm, data=build_data_source(settings), tracer=build_tracer(settings), settings=settings
    )
    judge_model = os.environ.get("JUDGE_MODEL", "").strip() or DEFAULT_JUDGE_MODEL
    if judge_model == "same" or settings.llm_mode != "live":
        judge_model = settings.llm_model
    if judge_model != settings.llm_model:
        judge_llm = build_llm_client(replace(settings, llm_model=judge_model))
        return deps, lambda: judge_llm, judge_model
    return deps, lambda: llm, settings.llm_model


def _summary(runs: Sequence[ScenarioRun]) -> list[str]:
    lines = []
    for r in runs:
        state = "pass" if r.passed else "FAIL"
        recall = f" recall {r.score.result.fact_recall:.0%}" if r.score else ""
        lines.append(f"{state:4} {r.scenario:12} {r.client:11}{recall}")
        for f in r.failures[:3]:
            lines.append(f"       - {f.check}: {f.detail}")
    return lines


async def _execute(
    scenarios: Sequence[Scenario],
    deps: RunDeps,
    run_fn: RunFn,
    judge_llm: LLMClient | None,
    judge_mode: str,
    judge_model: str,
) -> list[ScenarioRun]:
    from mpa.evals.runner import run_scenarios as run_all

    factory = (lambda: Judge(judge_llm)) if judge_llm is not None else None
    return await run_all(
        scenarios,
        deps,
        run_fn,
        judge_factory=factory,
        judge_mode="llm" if judge_mode == "llm" else "citations",
        judge_model=judge_model,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    run_fn: RunFn | None = None,
    deps: RunDeps | None = None,
    judge_llm: LLMClient | None = None,
    judge_model: str | None = None,
    now: datetime | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    scenarios = plan_scenarios(args.client, args.scenario)
    out_dir: Path = args.out or RESULTS_DIR
    mode = "replay" if args.replay else "live"
    try:
        if args.fake:
            from mpa.evals.fakes import FakeData, ScriptedJudge, fake_deps, make_run_fn

            deps = deps or fake_deps()
            run_fn = run_fn or make_run_fn()
            judge_llm = judge_llm or ScriptedJudge()
            judge_model = judge_model or "fake-judge"
            scenario_mod.DATA_SOURCE_BUILDER = lambda s: FakeData()  # type: ignore[assignment,return-value]
            mode = "fake (scripted, no LLM)"
            if args.out is None:
                out_dir = Path(tempfile.mkdtemp(prefix="mpa-evals-fake-"))
        elif deps is None:
            settings = replace(Settings.from_env(), llm_mode=mode)  # type: ignore[arg-type]
            deps, judge_factory_llm, resolved = _real_deps(settings)
            judge_llm = judge_llm or judge_factory_llm()
            judge_model = judge_model or resolved
            run_fn = run_fn or default_run_fn()
        else:
            run_fn = run_fn or default_run_fn()
            judge_model = judge_model or deps.settings.llm_model
            judge_llm = judge_llm or deps.llm
    except (ImportError, ValueError) as err:
        print(sanitize(f"cannot start: {type(err).__name__}: {err}"), file=sys.stderr)
        return 2

    try:
        runs = asyncio.run(
            _execute(scenarios, deps, run_fn, judge_llm, args.judge, judge_model or "unknown")
        )
    finally:
        cleanup_temp_dirs()
        scenario_mod.DATA_SOURCE_BUILDER = None
        try:
            deps.tracer.flush()
        except Exception:
            pass
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
    meta = ReportMeta(
        date=stamp,
        model=deps.settings.llm_model,
        judge_model=judge_model or deps.settings.llm_model,
        commit=git_commit(),
        mode=mode if args.judge == "llm" else f"{mode}, citation-coverage scoring",
    )
    paths = write_results(out_dir, runs, meta)
    print(sanitize("\n".join(_summary(runs))))
    print("wrote " + ", ".join(str(p) for p in paths))
    hard = any(r.hard_failed or (r.pack is None and r.error is not None) for r in runs)
    strict = args.strict and any(not r.passed for r in runs)
    return 1 if hard or strict else 0

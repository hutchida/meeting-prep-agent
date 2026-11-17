"""Run scenarios against `run_briefing` (or a fake) and score them."""

from __future__ import annotations

import asyncio
import importlib
import time
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any, Literal

from mpa.contract import (
    AgentEvent,
    BriefingPack,
    BriefingRequest,
    PackAssemblyError,
    RunDeps,
    assemble_pack,
)
from mpa.evals.gold import load_gold
from mpa.evals.judge import Judge, JudgeError, numbered_sentences, render_source
from mpa.evals.models import Failure, GoldFacts, ScenarioRun
from mpa.evals.scenarios import Scenario
from mpa.evals.scoring import (
    build_score,
    citation_judge,
    judge_trap_violations,
    outcomes_from_judgement,
    rule_trap_violations,
)

RunFn = Callable[[BriefingRequest, RunDeps], AsyncIterator[AgentEvent]]
JudgeFactory = Callable[[], Judge]
JudgeMode = Literal["llm", "citations"]


def default_run_fn() -> RunFn:
    run: RunFn = importlib.import_module("mpa.agents.orchestrator").run_briefing
    return run


async def collect_events(
    run_fn: RunFn, request: BriefingRequest, deps: RunDeps
) -> tuple[list[AgentEvent], str | None]:
    events: list[AgentEvent] = []
    try:
        async for event in run_fn(request, deps):
            events.append(event)
    except Exception as err:  # the orchestrator should not raise; record it if it does
        return events, f"run raised {type(err).__name__}: {str(err)[:200]}"
    return events, None


async def load_sources(deps: RunDeps, pack: BriefingPack) -> dict[str, str]:
    """Texts of every cited item, keyed `type:id`, fetched through the data source."""
    keys = sorted({c for s in numbered_sentences(pack) for c in s.citations})

    async def one(key: str) -> tuple[str, str]:
        ctype, cid = key.split(":", 1)
        try:
            return key, render_source(await deps.data.get_source(ctype, cid))  # type: ignore[arg-type]
        except Exception:
            return key, "(source unavailable)"

    return dict(await asyncio.gather(*(one(k) for k in keys)))


async def score_run(
    *,
    scenario: Scenario,
    deps: RunDeps,
    pack: BriefingPack,
    events: Sequence[AgentEvent],
    gold: GoldFacts,
    wall_ms: int,
    judge_model: str,
    judge_factory: JudgeFactory | None,
    judge_mode: JudgeMode,
) -> Any:
    sentences = numbered_sentences(pack)
    note: str | None = None
    calls = 0
    cost = 0.0
    mode: str = "citations"
    unsupported: list[Any] = []
    if judge_mode == "llm" and judge_factory is not None:
        judge = judge_factory()
        try:
            judgement = await judge.judge_facts(pack, gold)
            sources = await load_sources(deps, pack)
            unsupported = await judge.judge_claims(pack, sources)
            outcomes = outcomes_from_judgement(judgement, gold, sentences)
            violations = judge_trap_violations(judgement, sentences)
            mode = "llm"
        except (JudgeError, Exception) as err:
            note = f"judge failed ({type(err).__name__}: {str(err)[:160]}); used citation coverage"
            outcomes = citation_judge(pack, gold)
            violations = []
            unsupported = []
        calls, cost = judge.calls, judge.cost_usd
    else:
        outcomes = citation_judge(pack, gold)
        violations = []
        note = "citation-coverage scoring only (no LLM judge): recall counts cited source ids"
    violations = violations + rule_trap_violations(events, pack, gold)
    return build_score(
        client=scenario.client,
        scenario=scenario.name,
        pack=pack,
        events=events,
        gold=gold,
        outcomes=outcomes,
        violations=violations,
        unsupported=unsupported,
        wall_ms=wall_ms,
        judge_model=judge_model,
        judge_calls=calls,
        judge_cost_usd=cost,
        judge_mode=mode,
        judge_note=note,
    )


async def run_scenario(
    scenario: Scenario,
    deps: RunDeps,
    run_fn: RunFn,
    *,
    judge_factory: JudgeFactory | None,
    judge_mode: JudgeMode,
    judge_model: str,
) -> ScenarioRun:
    gold = load_gold(scenario.client)
    request = BriefingRequest(message=gold.user_prompt)
    run = ScenarioRun(client=scenario.client, scenario=scenario.name)
    try:
        run_deps, run_request = scenario.setup(deps, request)
    except Exception as err:
        run.error = f"setup failed: {type(err).__name__}: {str(err)[:200]}"
        run.failures = [Failure(check="setup", detail=run.error, hard=scenario.name != "normal")]
        return run
    started = time.perf_counter()
    events, run.error = await collect_events(run_fn, run_request, run_deps)
    run.wall_ms = int((time.perf_counter() - started) * 1000)
    run.event_count = len(events)
    pack: BriefingPack | None = None
    if events:
        try:
            pack = assemble_pack(events)
        except PackAssemblyError as err:
            run.error = (run.error + "; " if run.error else "") + f"no pack: {str(err)[:200]}"
    run.pack = pack
    run.failures = scenario.check(events, pack)
    if run.error and pack is None and not any(f.check == "no_briefing" for f in run.failures):
        run.failures.append(Failure(check="no_briefing", detail=run.error, hard=True))
    if pack is not None:
        run.score = await score_run(
            scenario=scenario,
            deps=run_deps,
            pack=pack,
            events=events,
            gold=gold,
            wall_ms=run.wall_ms,
            judge_model=judge_model,
            judge_factory=judge_factory,
            judge_mode=judge_mode,
        )
    return run


async def run_scenarios(
    scenarios: Sequence[Scenario],
    deps: RunDeps,
    run_fn: RunFn,
    *,
    judge_factory: JudgeFactory | None,
    judge_mode: JudgeMode,
    judge_model: str,
) -> list[ScenarioRun]:
    """Run all scenarios concurrently; results keep the order of `scenarios`."""
    return list(
        await asyncio.gather(
            *(
                run_scenario(
                    s,
                    deps,
                    run_fn,
                    judge_factory=judge_factory,
                    judge_mode=judge_mode,
                    judge_model=judge_model,
                )
                for s in scenarios
            )
        )
    )

"""Record the demo replay set (`make record`).

Runs the four demo requests live and writes the model responses to data/recordings/, where
LLM_MODE=replay serves them offline. It needs LITELLM_BASE_URL / LITELLM_API_KEY (names only here).

Why this is more than "RECORD=1": replay keys are a hash of the whole request, and a live model is
not deterministic. Two runs that start with the same requests (the normal Brightmoor run and the
news-outage run) would otherwise record different answers for the same key, and the later run
silently overwrites the earlier one, so the first run no longer replays as it was recorded. So each
scenario replays everything already accepted and only calls the model for requests not seen yet.

Each scenario is also gated on quality before it is accepted (all sections filled, enough talking
points, few verifier drops, and a flagged conflict where the gold data has one) and retried up to
`--attempts` times. If any scenario cannot pass, the existing recordings are left untouched.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from mpa.agents.orchestrator import run_briefing
from mpa.contract import (
    BriefingPack,
    BriefingRequest,
    LLMMessage,
    LLMResponse,
    NoopTracer,
    RunDeps,
    Settings,
    ToolSpec,
    assemble_pack,
)
from mpa.data import build_data_source
from mpa.llm import LiteLLMClient, RecordingClient, ReplayClient, ReplayMiss

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "evals" / "gold"
MIN_TALKING_POINTS = 3
MAX_DROPPED = 2


@dataclass(frozen=True)
class Scenario:
    name: str
    gold: str
    message: str
    fail_source: str | None = None


# Order matters: the outage run comes last so it replays the shared prefix of the normal run.
SCENARIOS = (
    Scenario("halden", "halden", "Prep me for my meeting with Halden Pay on Wednesday"),
    Scenario("brightmoor", "brightmoor", "Prep me for my meeting with Brightmoor on Thursday"),
    Scenario("kettle", "kettle", "Prep me for my meeting with Kettle & Crumb on Friday"),
    Scenario(
        "brightmoor_news_outage",
        "brightmoor",
        "Prep me for my meeting with Brightmoor on Thursday",
        "news",
    ),
)


class ReplayFirst:
    """Serve a request from earlier accepted recordings, else call the (recording) live client."""

    def __init__(self, replay: ReplayClient, live: RecordingClient) -> None:
        self._replay = replay
        self._live = live

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tag: str | None = None,
    ) -> LLMResponse:
        try:
            return await self._replay.chat(
                messages, tools=tools, temperature=temperature, max_tokens=max_tokens, tag=tag
            )
        except ReplayMiss:
            return await self._live.chat(
                messages, tools=tools, temperature=temperature, max_tokens=max_tokens, tag=tag
            )


def expects_conflict(gold: str) -> bool:
    facts = json.loads((GOLD / f"{gold}.facts.json").read_text())
    return any(t.get("kind") == "contradiction" for t in facts.get("traps", []))


def quality_problems(scenario: Scenario, pack: BriefingPack) -> list[str]:
    problems: list[str] = []
    for section in pack.sections:
        facts = [s for s in section.sentences if getattr(s, "kind", "fact") != "note"]
        news_down = scenario.fail_source == "news" and section.id == "recent_news"
        if not facts and not news_down:
            problems.append(f"section {section.id} has no factual sentence")
        if section.id == "talking_points_and_risks" and len(facts) < MIN_TALKING_POINTS:
            problems.append(f"only {len(facts)} talking points")
    if pack.verifier.sentences_dropped > MAX_DROPPED:
        problems.append(f"verifier dropped {pack.verifier.sentences_dropped} sentences")
    if pack.partial != (scenario.fail_source is not None):
        problems.append(f"partial={pack.partial} is not what this scenario should give")
    text = " ".join(s.text for sec in pack.sections for s in sec.sentences).lower()
    if expects_conflict(scenario.gold) and "disagree" not in text:
        problems.append("the dataset has a contradiction but the briefing does not flag one")
    return problems


async def run_once(scenario: Scenario, settings: Settings, llm: ReplayFirst) -> BriefingPack:
    deps = RunDeps(
        llm=llm, data=build_data_source(settings), tracer=NoopTracer(), settings=settings
    )
    request = BriefingRequest.model_validate(
        {"message": scenario.message, "fail_source": scenario.fail_source}
    )
    events = [e async for e in run_briefing(request, deps)]
    return assemble_pack(events)


def install(accepted: Path, out_dir: Path) -> list[Path]:
    """Replace the recordings in `out_dir` with the accepted set."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.json"):
        old.unlink()
    files = sorted(accepted.glob("*.json"))
    for f in files:
        shutil.copy2(f, out_dir / f.name)
    return files


async def record(attempts: int, out_dir: Path) -> int:
    load_dotenv(ROOT / ".env")
    env = dict(os.environ)
    env["LLM_MODE"] = "live"
    env.pop("RECORD", None)
    settings = Settings.from_env(env)
    live = LiteLLMClient(settings)
    work = Path(tempfile.mkdtemp(prefix="mpa-record-"))
    accepted = work / "accepted"
    accepted.mkdir()
    spend = 0.0
    try:
        for scenario in SCENARIOS:
            for attempt in range(1, attempts + 1):
                attempt_dir = work / f"{scenario.name}-{attempt}"
                attempt_dir.mkdir()
                llm = ReplayFirst(
                    ReplayClient(accepted, 0, model=settings.llm_model),
                    RecordingClient(live, attempt_dir, model=settings.llm_model),
                )
                pack = await run_once(scenario, settings, llm)
                spend += pack.stats.cost_usd
                problems = quality_problems(scenario, pack)
                label = "ok" if not problems else "retry: " + "; ".join(problems)
                print(f"{scenario.name} attempt {attempt}: {label}", flush=True)
                if not problems:
                    for f in attempt_dir.glob("*.json"):
                        shutil.copy2(f, accepted / f.name)
                    break
            else:
                print(f"no passing run for {scenario.name}; recordings left unchanged")
                return 1
        files = install(accepted, out_dir)
        print(
            f"wrote {len(files)} recordings; reported cost of the four runs ${spend:.3f} "
            "(replayed calls included, so live spend is lower)"
        )
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--attempts", type=int, default=6, help="live attempts per scenario")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "recordings")
    args = parser.parse_args()
    try:
        return asyncio.run(record(args.attempts, args.out))
    except Exception as exc:
        print(f"record failed: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

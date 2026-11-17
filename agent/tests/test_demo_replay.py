"""The committed recordings must replay the demo runs offline, with no key and no network."""

import pytest

from mpa.agents.orchestrator import run_briefing
from mpa.contract import BriefingRequest, NoopTracer, RunDeps, Settings, assemble_pack
from mpa.data import build_data_source
from mpa.llm import build_llm_client

CASES = [
    ("Prep me for my meeting with Halden Pay on Wednesday", None, False),
    ("Prep me for my meeting with Brightmoor on Thursday", None, False),
    ("Prep me for my meeting with Kettle & Crumb on Friday", None, False),
    ("Prep me for my meeting with Brightmoor on Thursday", "news", True),
]


@pytest.mark.parametrize(("message", "fail_source", "partial"), CASES)
async def test_demo_run_replays(message: str, fail_source: str | None, partial: bool) -> None:
    settings = Settings.from_env(
        {
            "LLM_MODEL": "vertex-ai-gemini-3-flash-preview",
            "LLM_MODE": "replay",
            "REPLAY_DELAY_MS": "0",
            "DEMO_NOW": "2026-03-09T09:00:00+00:00",
        }
    )
    deps = RunDeps(
        llm=build_llm_client(settings),
        data=build_data_source(settings),
        tracer=NoopTracer(),
        settings=settings,
    )
    request = BriefingRequest.model_validate({"message": message, "fail_source": fail_source})
    events = [e async for e in run_briefing(request, deps)]
    pack = assemble_pack(events)
    assert pack.partial is partial
    assert [g.source for g in pack.gaps] == (["news"] if partial else [])
    sections = {s.id: s for s in pack.sections}
    assert len(sections) == 7
    assert len(sections["talking_points_and_risks"].sentences) >= 3
    assert pack.verifier.sentences_dropped <= 2

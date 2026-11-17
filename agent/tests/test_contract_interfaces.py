"""Cross-task interfaces: Settings.from_env, the no-op tracer and protocol wiring."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import mpa.contract as contract
from mpa.contract import (
    DEFAULT_LLM_MODEL,
    DataSource,
    DataSourceError,
    LLMMessage,
    LLMResponse,
    NoopTracer,
    NullSpan,
    RunDeps,
    Settings,
    ToolCall,
    ToolSpec,
    Usage,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_settings_defaults() -> None:
    s = Settings.from_env({})
    assert s.llm_model == DEFAULT_LLM_MODEL == "vertex-ai-gemini-3-flash-preview"
    assert s.llm_mode == "replay"
    assert s.record is False
    assert s.data_source == "snapshot"
    assert s.data_dir == REPO_ROOT / "data"
    assert s.recordings_dir == REPO_ROOT / "data" / "recordings"
    assert s.demo_now == datetime(2026, 3, 9, 9, 0, tzinfo=UTC)
    assert s.fail_source is None
    assert s.max_steps_per_agent == 8
    assert s.max_tokens == 80_000
    assert s.max_cost_usd == 0.05
    assert s.subagent_timeout_s == 45.0
    assert s.replay_delay_ms == 250
    assert s.tracing == "off"


def test_settings_overrides() -> None:
    s = Settings.from_env(
        {
            "LLM_MODEL": "some-model",
            "LLM_MODE": "live",
            "RECORD": "1",
            "DATA_SOURCE": "graph",
            "MPA_DATA_DIR": "/tmp/d",
            "MPA_RECORDINGS_DIR": "/tmp/r",
            "DEMO_NOW": "2026-03-10T10:30:00+01:00",
            "FAIL_SOURCE": "news",
            "MAX_STEPS_PER_AGENT": "3",
            "MAX_TOKENS": "1000",
            "MAX_COST_USD": "0.2",
            "REPLAY_DELAY_MS": "0",
            "TRACING": "langfuse",
        }
    )
    assert (s.llm_model, s.llm_mode, s.record, s.data_source) == (
        "some-model",
        "live",
        True,
        "graph",
    )
    assert s.data_dir == Path("/tmp/d") and s.recordings_dir == Path("/tmp/r")
    assert s.demo_now == datetime(2026, 3, 10, 9, 30, tzinfo=UTC)
    assert s.fail_source == "news"
    assert (s.max_steps_per_agent, s.max_tokens, s.max_cost_usd) == (3, 1000, 0.2)
    assert (s.replay_delay_ms, s.tracing) == (0, "langfuse")


def test_settings_accepts_the_env_file_demo_now_and_treats_empty_as_unset() -> None:
    s = Settings.from_env(
        {"DEMO_NOW": "2026-03-09T09:00:00+00:00", "FAIL_SOURCE": "", "RECORD": ""}
    )
    assert s.demo_now == datetime(2026, 3, 9, 9, 0, tzinfo=UTC)
    assert s.fail_source is None and s.record is False
    assert Settings.from_env({"DEMO_NOW": "2026-03-09T09:00:00Z"}).demo_now.tzinfo is not None
    assert Settings.from_env({"DEMO_NOW": "2026-03-09T09:00:00"}).demo_now.tzinfo == UTC


@pytest.mark.parametrize(
    "env",
    [
        {"LLM_MODE": "maybe"},
        {"DATA_SOURCE": "sql"},
        {"TRACING": "datadog"},
        {"FAIL_SOURCE": "chat"},
        {"MAX_TOKENS": "lots"},
        {"DEMO_NOW": "tomorrow"},
    ],
)
def test_settings_rejects_bad_values(env: dict[str, str]) -> None:
    with pytest.raises(ValueError, match=next(iter(env))):
        Settings.from_env(env)


def test_settings_is_frozen_and_reads_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "from-os-environ")
    s = Settings.from_env()
    assert s.llm_model == "from-os-environ"
    with pytest.raises(AttributeError):
        s.llm_model = "x"  # type: ignore[misc]


def test_noop_tracer_is_a_no_op() -> None:
    tracer = NoopTracer()
    run = tracer.start_run("run_1", name="briefing", input={"message": "hi"})
    child = tracer.start_span(run, "news", kind="agent", input={"a": 1})
    tool = tracer.start_span(child, "search_news", kind="tool")
    assert isinstance(run, NullSpan) and isinstance(child, NullSpan) and isinstance(tool, NullSpan)
    tracer.record_llm(child, model="m", input=[], output="x", usage=Usage(), latency_ms=5)
    run.set(anything=object())
    tool.end()
    child.end(error="boom")
    tracer.flush()


def test_llm_types_round_trip() -> None:
    call = ToolCall(id="call_1", name="search_news", arguments={"query": "x"})
    msg = LLMMessage(role="assistant", tool_calls=[call])
    resp = LLMResponse(message=msg, usage=Usage(prompt_tokens=3, completion_tokens=2), model="m")
    assert LLMResponse.model_validate_json(resp.model_dump_json()) == resp
    assert resp.finish_reason is None and resp.latency_ms == 0 and resp.usage.cost_usd == 0.0
    spec = ToolSpec(name="t", description="d", parameters={"type": "object", "properties": {}})
    assert spec.parameters["type"] == "object"


class _FakeLLM:
    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tag: str | None = None,
    ) -> LLMResponse:
        return LLMResponse(
            message=LLMMessage(role="assistant", content="ok"), usage=Usage(), model="fake"
        )


async def test_run_deps_accepts_protocol_implementations() -> None:
    deps = RunDeps(
        llm=_FakeLLM(),
        data=None,  # type: ignore[arg-type]
        tracer=NoopTracer(),
        settings=Settings.from_env({}),
    )
    reply = await deps.llm.chat([LLMMessage(role="user", content="hi")], tag="t")
    assert reply.message.content == "ok"


def test_everything_is_exported_from_the_package() -> None:
    for name in (
        "CitationType", "DataSource", "DataSourceError", "LLMClient", "LLMMessage", "LLMResponse",
        "NoopTracer", "NullSpan", "RunDeps", "Settings", "Span", "ToolCall", "ToolSpec", "Tracer",
        "Usage", "Email", "SearchHit", "SourceItem", "BriefingPack", "AgentEvent", "EvalResult",
    ):  # fmt: skip
        assert hasattr(contract, name), name
    assert issubclass(DataSourceError, Exception) and not issubclass(DataSourceError, KeyError)
    assert DataSource.__name__ == "DataSource"

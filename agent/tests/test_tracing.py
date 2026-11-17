"""Tracing: build_tracer fallbacks and the Langfuse tracer against a fake client. Offline."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import pytest

from mpa.contract import NoopTracer, Settings, Usage
from mpa.tracing import LangfuseTracer, build_tracer
from mpa.tracing import langfuse_tracer as lf_module

PUBLIC = "pk-test-public-123456"
SECRET = "sk-test-secret-123456"
HOST = "http://langfuse.internal.example:3100"
ENV = {"LANGFUSE_PUBLIC_KEY": PUBLIC, "LANGFUSE_SECRET_KEY": SECRET, "LANGFUSE_HOST": HOST}
ON = Settings(llm_model="m", tracing="langfuse")


class FakeObservation:
    def __init__(self, client: FakeClient, kind: str, parent: FakeObservation | None, kw: Any):
        self.client = client
        self.kind = kind
        self.parent = parent
        self.kw = dict(kw)
        self.updates: list[dict[str, Any]] = []
        self.ended: dict[str, Any] | None = None

    def span(self, **kw: Any) -> FakeObservation:
        return self.client.make("span", self, kw)

    def generation(self, **kw: Any) -> FakeObservation:
        return self.client.make("generation", self, kw)

    def update(self, **kw: Any) -> FakeObservation:
        self.updates.append(kw)
        return self

    def end(self, **kw: Any) -> FakeObservation:
        self.ended = kw
        return self


class FakeClient:
    def __init__(self) -> None:
        self.observations: list[FakeObservation] = []
        self.flushed = 0

    def make(self, kind: str, parent: FakeObservation | None, kw: Any) -> FakeObservation:
        obs = FakeObservation(self, kind, parent, kw)
        self.observations.append(obs)
        return obs

    def trace(self, **kw: Any) -> FakeObservation:
        return self.make("trace", None, kw)

    def flush(self) -> None:
        self.flushed += 1


class ExplodingClient:
    """`trace` works, everything else raises with a message full of secrets."""

    def trace(self, **kw: Any) -> ExplodingClient:
        return self

    def __getattr__(self, name: str) -> Any:
        def boom(*_: Any, **__: Any) -> Any:
            raise RuntimeError(f"{HOST} {SECRET}")

        return boom


def warnings_of(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.WARNING and r.name == "mpa.tracing"]


# ---------------------------------------------------------------- build_tracer


def test_off_returns_noop() -> None:
    assert isinstance(build_tracer(Settings(llm_model="m", tracing="off"), env=ENV), NoopTracer)


@pytest.mark.parametrize(
    ("env", "reason"),
    [
        ({}, "keys_missing"),
        ({"LANGFUSE_PUBLIC_KEY": PUBLIC, "LANGFUSE_HOST": HOST}, "keys_missing"),
        ({"LANGFUSE_PUBLIC_KEY": PUBLIC, "LANGFUSE_SECRET_KEY": SECRET}, "host_missing"),
        ({**ENV, "LANGFUSE_HOST": "not-a-url"}, "host_missing"),
    ],
)
def test_missing_configuration_falls_back_with_one_warning(
    env: dict[str, str], reason: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="mpa.tracing")
    tracer = build_tracer(ON, env=env, client_factory=lambda *_: FakeClient(), probe=lambda _: True)
    assert isinstance(tracer, NoopTracer)
    records = warnings_of(caplog)
    assert len(records) == 1 and reason in records[0].getMessage()
    for value in (PUBLIC, SECRET, HOST):
        assert value not in caplog.text


def test_missing_package_falls_back(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("mpa.tracing._package_available", lambda: False)
    tracer = build_tracer(ON, env=ENV, probe=lambda _: True)
    assert isinstance(tracer, NoopTracer)
    records = warnings_of(caplog)
    assert len(records) == 1 and "package_missing" in records[0].getMessage()


def test_import_error_in_client_factory_falls_back(caplog: pytest.LogCaptureFixture) -> None:
    def factory(*_: str) -> Any:
        raise ImportError(f"cannot import {HOST} {SECRET}")

    tracer = build_tracer(ON, env=ENV, client_factory=factory, probe=lambda _: True)
    assert isinstance(tracer, NoopTracer)
    assert len(warnings_of(caplog)) == 1
    assert SECRET not in caplog.text and HOST not in caplog.text


def test_unreachable_host_falls_back(caplog: pytest.LogCaptureFixture) -> None:
    created: list[str] = []

    def factory(*_: str) -> FakeClient:
        created.append("x")
        return FakeClient()

    tracer = build_tracer(
        ON,
        env=ENV,
        client_factory=factory,
        probe=lambda host: False,
    )
    assert isinstance(tracer, NoopTracer)
    assert created == []
    records = warnings_of(caplog)
    assert len(records) == 1 and "unreachable" in records[0].getMessage()
    assert HOST not in caplog.text


def test_real_probe_of_a_closed_port_is_unreachable(caplog: pytest.LogCaptureFixture) -> None:
    env = {**ENV, "LANGFUSE_HOST": "http://127.0.0.1:9"}
    started = time.monotonic()
    tracer = build_tracer(ON, env=env, client_factory=lambda *_: FakeClient())
    assert isinstance(tracer, NoopTracer)
    assert time.monotonic() - started < 5
    assert len(warnings_of(caplog)) == 1 and "127.0.0.1" not in caplog.text


def test_configured_langfuse_returns_langfuse_tracer(caplog: pytest.LogCaptureFixture) -> None:
    seen: list[tuple[str, str, str]] = []

    def factory(public: str, secret: str, host: str) -> FakeClient:
        seen.append((public, secret, host))
        return FakeClient()

    tracer = build_tracer(ON, env=ENV, client_factory=factory, probe=lambda _: True)
    assert isinstance(tracer, LangfuseTracer)
    assert seen == [(PUBLIC, SECRET, HOST)]
    assert warnings_of(caplog) == []


# ---------------------------------------------------------------- LangfuseTracer


def test_trace_structure_nesting_and_llm_generation() -> None:
    client = FakeClient()
    tracer = LangfuseTracer(client, secrets=())
    run = tracer.start_run("run_1", name="briefing", input={"message": "hello"})
    agent = tracer.start_span(run, "news", kind="agent", input={"goal": "find news"})
    step = tracer.start_span(agent, "step 1", kind="step")
    tool = tracer.start_span(step, "search_news", kind="tool", input={"query": "acme"})
    tool.set(output={"item_count": 2})
    tool.end()
    tracer.record_llm(
        step,
        model="some-model",
        input=[{"role": "user", "content": "hi"}],
        output={"role": "assistant", "content": "ok"},
        usage=Usage(prompt_tokens=120, completion_tokens=30, cost_usd=0.0021),
        latency_ms=800,
    )
    step.end()
    agent.end(error="timeout")
    run.set(output={"partial": True})
    run.end()
    tracer.flush()

    trace, agent_obs, step_obs, tool_obs, gen = client.observations
    assert trace.kind == "trace" and trace.kw["id"] == "run_1" and trace.kw["name"] == "briefing"
    assert (agent_obs.parent, step_obs.parent, tool_obs.parent) == (trace, agent_obs, step_obs)
    assert gen.parent is step_obs and gen.kind == "generation"
    assert gen.kw["model"] == "some-model"
    assert gen.kw["usage"] == {
        "input": 120,
        "output": 30,
        "total": 150,
        "unit": "TOKENS",
        "total_cost": 0.0021,
    }
    assert gen.kw["input"] == [{"role": "user", "content": "hi"}]
    assert gen.kw["output"] == {"role": "assistant", "content": "ok"}
    assert gen.kw["metadata"] == {"latency_ms": 800}
    assert gen.kw["end_time"] > gen.kw["start_time"]
    assert agent_obs.kw["metadata"] == {"kind": "agent"}
    assert tool_obs.updates[0]["output"] == {"item_count": 2}
    assert tool_obs.ended is not None and "level" not in tool_obs.ended
    assert agent_obs.ended is not None and agent_obs.ended["level"] == "ERROR"
    assert agent_obs.ended["status_message"] == "timeout"
    assert trace.updates[0]["output"] == {"partial": True}
    assert client.flushed == 1


def test_llm_kind_span_is_a_generation_and_end_is_idempotent() -> None:
    client = FakeClient()
    tracer = LangfuseTracer(client, secrets=())
    run = tracer.start_run("r", name="n", input={})
    span = tracer.start_span(run, "call", kind="llm")
    span.set(model="m1", output="x", tokens=3)
    span.end()
    span.end(error="late")
    span.set(output="ignored")
    gen = client.observations[1]
    assert gen.kind == "generation"
    assert gen.updates[0]["model"] == "m1" and gen.updates[0]["metadata"]["tokens"] == 3
    assert gen.ended is not None and "level" not in gen.ended
    assert len(gen.updates) == 1


def test_foreign_parent_is_ignored() -> None:
    client = FakeClient()
    tracer = LangfuseTracer(client, secrets=())
    foreign = NoopTracer().start_run("x", name="n", input={})
    child = tracer.start_span(foreign, "s", kind="step")
    child.set(a=1)
    child.end()
    tracer.record_llm(foreign, model="m", input=1, output=2, usage=Usage(), latency_ms=1)
    assert client.observations == []


def test_tracer_never_raises_and_disables_itself_after_repeated_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tracer = LangfuseTracer(ExplodingClient(), secrets=(HOST, SECRET))
    run = tracer.start_run("r", name="n", input={"k": "v"})
    for _ in range(10):
        child = tracer.start_span(run, "s", kind="tool", input={"a": 1})
        child.set(x=1)
        child.end(error="bad")
        tracer.record_llm(run, model="m", input=1, output=2, usage=Usage(), latency_ms=5)
    run.end()
    tracer.flush()
    assert tracer._disabled
    assert len(warnings_of(caplog)) == 1
    assert HOST not in caplog.text and SECRET not in caplog.text


def test_flush_is_bounded_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()

    class Hanging(FakeClient):
        def flush(self) -> None:
            release.wait(10)

    monkeypatch.setattr(lf_module, "FLUSH_TIMEOUT_S", 0.2)
    tracer = LangfuseTracer(Hanging(), secrets=())
    started = time.monotonic()
    tracer.flush()
    assert time.monotonic() - started < 2
    release.set()
    LangfuseTracer(ExplodingClient(), secrets=()).flush()


def test_content_is_truncated_and_scrubbed() -> None:
    client = FakeClient()
    tracer = LangfuseTracer(client, secrets=(SECRET, HOST))
    run = tracer.start_run("r", name="n", input={"message": "see https://example.com/a?b=1"})
    big = "x" * 50_000
    payload = {
        "text": big,
        "headers": {"Authorization": "Bearer abcdef123456"},
        "api_key": SECRET,
        "note": f"calling {HOST}/v1 with {SECRET}",
        "nested": {"url": "https://example.org", "ok": 1},
    }
    span = tracer.start_span(run, "tool", kind="tool", input=payload)
    span.set(output=big)
    trace, tool = client.observations
    assert trace.kw["input"] == {"message": "see [url]"}
    sent = tool.kw["input"]
    assert isinstance(sent, str) and len(sent) < 4200 and "truncated" in sent
    assert tool.updates[0]["output"].endswith("chars]") and len(tool.updates[0]["output"]) < 4200

    small = {k: v for k, v in payload.items() if k != "text"}
    span2 = tracer.start_span(run, "tool2", kind="tool", input=small)
    shown = client.observations[-1].kw["input"]
    text = str(shown)
    assert SECRET not in text and HOST not in text and "abcdef123456" not in text
    assert "example.org" not in text
    assert shown["headers"] == "[redacted]" and shown["api_key"] == "[redacted]"
    assert shown["nested"] == {"url": "[redacted]", "ok": 1}
    span2.end()


def test_pydantic_values_and_odd_objects_are_accepted() -> None:
    client = FakeClient()
    tracer = LangfuseTracer(client, secrets=())
    run = tracer.start_run("r", name="n", input={"usage": Usage(prompt_tokens=1), "o": object()})
    assert run is not None
    assert client.observations[0].kw["input"]["usage"]["prompt_tokens"] == 1
    assert client.observations[0].kw["input"]["o"] == "<object>"

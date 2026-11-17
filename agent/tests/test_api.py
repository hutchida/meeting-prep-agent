"""API routes: health, SSE streaming, sources, CORS, error paths. Fully offline."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import time
import types
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from mpa.api.app import app as module_app
from mpa.api.app import create_app
from mpa.contract import (
    AgentEvent,
    BriefingRequest,
    DataSourceError,
    NoopTracer,
    RunDeps,
    Settings,
    SourceItem,
    assemble_pack,
    check_event_order,
)
from test_api_support import (
    AsgiCall,
    Untouchable,
    fixture,
    make_deps,
    parse_sse,
    replay_run,
    run_events,
)

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "packages" / "contract" / "schema"
REQUEST_BODY = json.dumps({"message": "Prep me for my Thursday meeting with Brightmoor"}).encode()
JSON_HEADERS = {"content-type": "application/json"}


def brief(app: FastAPI, **kwargs: Any) -> AsgiCall:
    return AsgiCall(app, "POST", "/briefings", REQUEST_BODY, **kwargs).start()


def sse_events(raw: bytes) -> list[dict[str, Any]]:
    return [m for m in parse_sse(raw) if "event" in m]


# ---------------------------------------------------------------- health


def test_module_app_health_is_fast_and_shaped() -> None:
    client = TestClient(module_app)
    started = time.monotonic()
    res = client.get("/health")
    assert time.monotonic() - started < 1.0
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"status", "version", "llm_mode", "data_source", "tracing"}
    assert body["status"] == "ok"


def test_health_reports_settings_and_never_touches_llm_or_data() -> None:
    client = TestClient(create_app(deps=make_deps()))
    body = client.get("/health").json()
    assert body["llm_mode"] == "replay"
    assert body["data_source"] == "snapshot"
    assert body["tracing"] == "off"
    text = json.dumps(body)
    assert "http" not in text and "key" not in text.lower()


def test_health_survives_broken_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: Any, **__: Any) -> Settings:
        raise ValueError("LLM_MODE must be one of live, replay; got 'x'")

    monkeypatch.setattr(Settings, "from_env", boom)
    res = TestClient(create_app()).get("/health")
    assert res.status_code == 200
    assert res.json()["llm_mode"] == "unknown"


# ---------------------------------------------------------------- SSE


async def test_stream_framing_order_and_end() -> None:
    events = run_events()
    call = brief(create_app(run_fn=replay_run(events), deps=make_deps()))
    raw = await call.wait_done()
    assert call.status == 200
    assert call.headers["content-type"].startswith("text/event-stream")
    assert call.headers["cache-control"] == "no-cache"
    assert call.headers["x-accel-buffering"] == "no"
    messages = parse_sse(raw)
    assert messages[0] == {"comment": "stream-open"}
    sent = sse_events(raw)
    assert [m["data"] for m in sent] == events
    assert [m["event"] for m in sent] == [e["type"] for e in events]
    for m in sent:
        assert m["raw"] == json.dumps(m["data"], separators=(",", ":"), ensure_ascii=False)
        assert len(m["raw"].encode()) <= 8192
    assert sent[-1]["event"] == "run_done"
    assert check_event_order([AgentEvent.model_validate(m["data"]) for m in sent]) == []
    assert assemble_pack([m["data"] for m in sent]).run_id == events[0]["run_id"]


async def test_stream_payloads_validate_against_json_schema() -> None:
    validator = Draft202012Validator(json.loads((SCHEMA_DIR / "AgentEvent.json").read_text()))
    for name in ("run.brightmoor.normal", "run.brightmoor.news_down", "run.halden.budget_hit"):
        events = run_events(name)
        call = brief(create_app(run_fn=replay_run(events), deps=make_deps()))
        sent = sse_events(await call.wait_done())
        assert len(sent) == len(events)
        for message in sent:
            assert not list(validator.iter_errors(message["data"]))


async def test_first_frame_arrives_immediately_even_if_run_is_slow() -> None:
    async def slow(request: BriefingRequest, deps: RunDeps) -> AsyncIterator[AgentEvent]:
        await asyncio.sleep(30)
        yield AgentEvent.model_validate(run_events()[0])

    call = brief(create_app(run_fn=slow, deps=make_deps()))
    await call.wait_for_chunks(1, within=3)
    assert call.chunks, "no bytes within 3 s"
    assert call.chunks[0][0] < 0.5
    assert call.chunks[0][1] == b": stream-open\n\n"
    call.disconnect()
    await call.wait_done()


async def test_keepalive_comments_while_waiting() -> None:
    async def slow(request: BriefingRequest, deps: RunDeps) -> AsyncIterator[AgentEvent]:
        await asyncio.sleep(0.4)
        for event in run_events():
            yield AgentEvent.model_validate(event)

    call = brief(create_app(run_fn=slow, deps=make_deps(), keepalive_s=0.05))
    raw = await call.wait_done()
    assert [m for m in parse_sse(raw) if m.get("comment") == "keep-alive"]
    assert sse_events(raw)[-1]["event"] == "run_done"


async def test_events_after_run_done_are_not_sent() -> None:
    events = run_events()
    extra = [*events, {**events[-1], "seq": events[-1]["seq"] + 1}]
    call = brief(create_app(run_fn=replay_run(extra), deps=make_deps()))
    assert len(sse_events(await call.wait_done())) == len(events)


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"{}",
        b'{"message":""}',
        b'{"message":"x","extra":1}',
        b'{"message":"x","fail_source":"bad"}',
        b"not json",
    ],
)
def test_bad_body_is_422_without_echoing_input(body: bytes) -> None:
    client = TestClient(create_app(run_fn=replay_run([]), deps=make_deps()))
    res = client.post("/briefings", content=body, headers=JSON_HEADERS)
    assert res.status_code == 422
    assert res.json()["error"] == "validation_error"
    assert "not json" not in res.text


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
async def test_client_disconnect_cancels_the_run(spec_version: str) -> None:
    state = {"started": False, "cancelled": False, "child_cancelled": False}

    async def long_run(request: BriefingRequest, deps: RunDeps) -> AsyncIterator[AgentEvent]:
        async def child() -> None:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                state["child_cancelled"] = True
                raise

        task = asyncio.create_task(child())
        try:
            state["started"] = True
            yield AgentEvent.model_validate(run_events()[0])
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    call = brief(create_app(run_fn=long_run, deps=make_deps()), spec_version=spec_version)
    await call.wait_for_chunks(2, within=3)
    assert state["started"]
    call.disconnect()
    await asyncio.wait_for(call.finished.wait(), 3)
    for _ in range(50):
        if state["cancelled"] and state["child_cancelled"]:
            break
        await asyncio.sleep(0.02)
    assert state["cancelled"] and state["child_cancelled"]
    leftover = [t for t in asyncio.all_tasks() if t.get_name() == "briefing-run" and not t.done()]
    assert leftover == []


async def test_disconnect_while_a_frame_was_just_sent_still_cancels() -> None:
    cancelled = asyncio.Event()

    async def run(request: BriefingRequest, deps: RunDeps) -> AsyncIterator[AgentEvent]:
        try:
            for event in run_events()[:3]:
                yield AgentEvent.model_validate(event)
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    call = brief(create_app(run_fn=run, deps=make_deps()), spec_version="2.4")
    await call.wait_for_chunks(4, within=3)
    call.disconnect()
    await asyncio.wait_for(cancelled.wait(), 3)


def assert_safe_terminal(raw: bytes) -> list[dict[str, Any]]:
    sent = sse_events(raw)
    last = sent[-1]
    assert last["event"] == "run_done"
    assert last["data"]["partial"] is True
    AgentEvent.model_validate(last["data"])
    seqs = [m["data"]["seq"] for m in sent]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert b"Traceback" not in raw and b"http" not in raw and b"sk-" not in raw
    return sent


async def test_run_fn_exception_becomes_partial_run_done() -> None:
    events = run_events()[:6]

    async def failing(request: BriefingRequest, deps: RunDeps) -> AsyncIterator[AgentEvent]:
        for event in events:
            yield AgentEvent.model_validate(event)
        raise RuntimeError("boom https://secret.example/x sk-abc123456789 Traceback")

    raw = await brief(create_app(run_fn=failing, deps=make_deps())).wait_done()
    assert b"boom" not in raw and b"secret.example" not in raw
    sent = assert_safe_terminal(raw)
    started = {m["data"]["agent"] for m in sent if m["event"] == "subagent_started"}
    failed = {m["data"]["agent"] for m in sent if m["event"] == "subagent_failed"}
    assert started and started <= failed
    pack = assemble_pack([m["data"] for m in sent])
    assert pack.partial is True
    assert all(section.empty for section in pack.sections)
    drafts = [m["data"] for m in sent if m["event"] == "draft"]
    assert len(drafts) == 7 and [d["complete"] for d in drafts] == [False] * 6 + [True]
    assert check_event_order([m["data"] for m in sent]) == []


async def test_exception_in_the_middle_of_drafts_completes_the_remaining_sections() -> None:
    events = run_events()
    drafts = [i for i, e in enumerate(events) if e["type"] == "draft"]
    cut = events[: drafts[3] + 1]

    async def failing(request: BriefingRequest, deps: RunDeps) -> AsyncIterator[AgentEvent]:
        for event in cut:
            yield AgentEvent.model_validate(event)
        raise RuntimeError("late failure")

    sent = assert_safe_terminal(
        await brief(create_app(run_fn=failing, deps=make_deps())).wait_done()
    )
    sent_drafts = [m["data"] for m in sent if m["event"] == "draft"]
    assert len(sent_drafts) == 7
    assert [d["complete"] for d in sent_drafts] == [False] * 6 + [True]
    assert check_event_order([m["data"] for m in sent]) == []
    assert assemble_pack([m["data"] for m in sent]).partial is True


async def test_exception_before_first_event_still_ends_with_run_done() -> None:
    async def failing(request: BriefingRequest, deps: RunDeps) -> AsyncIterator[AgentEvent]:
        raise ValueError("early")
        yield  # pragma: no cover

    sent = assert_safe_terminal(
        await brief(create_app(run_fn=failing, deps=make_deps())).wait_done()
    )
    assert len(sent) == 1 and sent[0]["data"]["seq"] == 0


async def test_stream_that_ends_without_run_done_gets_one() -> None:
    call = brief(create_app(run_fn=replay_run(run_events()[:3]), deps=make_deps()))
    sent = assert_safe_terminal(await call.wait_done())
    assert [m["event"] for m in sent][:3] == ["run_started", "plan", "subagent_started"]


async def test_invalid_event_is_replaced_by_a_safe_terminal_event() -> None:
    events = run_events()

    async def run(request: BriefingRequest, deps: RunDeps) -> AsyncIterator[Any]:
        yield events[0]
        yield {"type": "plan", "run_id": events[0]["run_id"], "seq": 1, "bogus": True}
        yield events[2]

    sent = assert_safe_terminal(await brief(create_app(run_fn=run, deps=make_deps())).wait_done())
    assert [m["event"] for m in sent] == ["run_started", "run_done"]
    assert sent[-1]["data"]["seq"] == 1


async def test_oversized_event_is_replaced_by_a_safe_terminal_event() -> None:
    big = json.loads(json.dumps(next(e for e in run_events() if e["type"] == "draft")))
    big["sections"][0]["sentences"] = [
        {"text": "x" * 2000, "citations": [{"type": "email", "id": "E1"}]} for _ in range(6)
    ]

    async def run(request: BriefingRequest, deps: RunDeps) -> AsyncIterator[Any]:
        yield run_events()[0]
        yield big

    sent = assert_safe_terminal(await brief(create_app(run_fn=run, deps=make_deps())).wait_done())
    assert [m["event"] for m in sent] == ["run_started", "run_done"]
    assert all(len(m["raw"].encode()) <= 8192 for m in sent)


async def test_default_run_fn_and_deps_are_built_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[str] = []
    events = run_events()
    settings = Settings(llm_model="lazy-model", tracing="off")
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls, env=None: settings))

    def build_llm(_: Settings) -> Untouchable:
        built.append("llm")
        return Untouchable()

    def build_data(_: Settings) -> Untouchable:
        built.append("data")
        return Untouchable()

    llm_mod = types.ModuleType("mpa.llm")
    llm_mod.build_llm_client = build_llm  # type: ignore[attr-defined]
    data_mod = types.ModuleType("mpa.data")
    data_mod.build_data_source = build_data  # type: ignore[attr-defined]
    orch_mod = types.ModuleType("mpa.agents.orchestrator")
    orch_mod.run_briefing = replay_run(events)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mpa.llm", llm_mod)
    monkeypatch.setitem(sys.modules, "mpa.data", data_mod)
    monkeypatch.setitem(sys.modules, "mpa.agents.orchestrator", orch_mod)

    app = create_app()
    assert built == []
    assert TestClient(app).get("/health").status_code == 200
    assert built == []
    assert len(sse_events(await brief(app).wait_done())) == len(events)
    assert sorted(built) == ["data", "llm"]
    assert isinstance(app, FastAPI) and NoopTracer is not None


async def test_missing_orchestrator_or_builders_is_503_for_that_route_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "mpa.agents.orchestrator", types.ModuleType("x"))
    monkeypatch.setitem(sys.modules, "mpa.data", types.ModuleType("mpa.data"))
    client = TestClient(create_app())
    res = client.post("/briefings", content=REQUEST_BODY, headers=JSON_HEADERS)
    assert res.status_code == 503 and res.json() == {"error": "service_unavailable"}
    assert client.get("/sources/email/E1").status_code == 503
    assert client.get("/health").status_code == 200


async def test_briefing_with_failing_dependency_builders_is_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*_: Any) -> Any:
        raise RuntimeError("no https://litellm.example key")

    llm_mod = types.ModuleType("mpa.llm")
    llm_mod.build_llm_client = broken  # type: ignore[attr-defined]
    data_mod = types.ModuleType("mpa.data")
    data_mod.build_data_source = lambda s: Untouchable()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mpa.llm", llm_mod)
    monkeypatch.setitem(sys.modules, "mpa.data", data_mod)
    client = TestClient(create_app(run_fn=replay_run([])))
    res = client.post("/briefings", content=REQUEST_BODY, headers=JSON_HEADERS)
    assert res.status_code == 503
    assert res.json() == {"error": "service_unavailable"}


def test_real_server_first_event_latency_and_streaming() -> None:
    events = run_events()

    async def paced(request: BriefingRequest, deps: RunDeps) -> AsyncIterator[AgentEvent]:
        for i, event in enumerate(events[:8]):
            if i:
                await asyncio.sleep(0.15)
            yield AgentEvent.model_validate(event)
        yield AgentEvent.model_validate({**events[-1], "seq": events[7]["seq"] + 1})

    server = uvicorn.Server(
        uvicorn.Config(
            create_app(run_fn=paced, deps=make_deps()),
            host="127.0.0.1",
            port=0,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        port = server.servers[0].sockets[0].getsockname()[1]
        started = time.monotonic()
        arrivals: list[tuple[float, str]] = []
        with httpx.stream(
            "POST",
            f"http://127.0.0.1:{port}/briefings",
            content=REQUEST_BODY,
            headers=JSON_HEADERS,
            timeout=10,
        ) as res:
            assert res.headers["content-type"].startswith("text/event-stream")
            for line in res.iter_lines():
                if line.startswith("event:"):
                    arrivals.append((time.monotonic() - started, line))
        assert arrivals[0][0] < 1.0
        assert arrivals[-1][0] - arrivals[0][0] > 0.5, "events must stream, not arrive in a burst"
        assert arrivals[-1][1] == "event: run_done"
    finally:
        server.should_exit = True
        thread.join(5)


# ---------------------------------------------------------------- sources

SOURCE_FIXTURES = {
    "email": "Email.basic",
    "chat": "ChatMessage.basic",
    "doc": "Doc.basic",
    "news": "NewsItem.basic",
    "contact": "Contact.basic",
    "cal": "CalendarEvent.basic",
}


class FakeData:
    def __init__(self) -> None:
        self.items = {(t, fixture(n)["id"]): fixture(n) for t, n in SOURCE_FIXTURES.items()}

    async def get_source(self, type: str, id: str) -> SourceItem:
        if id == "E999999":
            raise DataSourceError("temporarily down")
        if id == "E888888":
            raise NotImplementedError
        try:
            return SourceItem.model_validate(self.items[(type, id)])
        except KeyError:
            raise KeyError(id) from None


@pytest.mark.parametrize("kind", sorted(SOURCE_FIXTURES))
def test_sources_returns_each_type(kind: str) -> None:
    client = TestClient(create_app(deps=make_deps(data=FakeData())))
    expected = fixture(SOURCE_FIXTURES[kind])
    res = client.get(f"/sources/{kind}/{expected['id']}")
    assert res.status_code == 200
    assert res.json() == expected


def test_sources_not_found_and_validation() -> None:
    client = TestClient(create_app(deps=make_deps(data=FakeData())))
    not_found = client.get("/sources/email/E12345")
    assert not_found.status_code == 404 and not_found.json() == {"error": "not_found"}
    assert client.get("/sources/invoice/E1").status_code == 422
    assert client.get("/sources/email/C37").status_code == 422
    assert client.get("/sources/email/E").status_code == 422
    assert client.get("/sources/email/E1234567890").status_code == 422
    assert client.get("/sources/doc/D%2e%2e").status_code == 422
    assert client.get("/sources/cal/M2").status_code == 200


def test_sources_transient_failure_is_503() -> None:
    client = TestClient(create_app(deps=make_deps(data=FakeData())))
    for item_id in ("E999999", "E888888"):
        res = client.get(f"/sources/email/{item_id}")
        assert res.status_code == 503 and res.json() == {"error": "service_unavailable"}


# ---------------------------------------------------------------- CORS and logging


@pytest.mark.parametrize("origin", ["http://localhost:3000", "http://127.0.0.1:3000"])
def test_cors_allows_the_web_app(origin: str) -> None:
    client = TestClient(create_app(deps=make_deps()))
    pre = client.options(
        "/briefings",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert pre.status_code == 200
    assert pre.headers["access-control-allow-origin"] == origin
    methods = set(pre.headers["access-control-allow-methods"].split(", "))
    assert methods == {"GET", "POST", "OPTIONS"}
    simple = client.get("/health", headers={"Origin": origin})
    assert simple.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("origin", ["http://evil.example", "http://localhost:3001", "null"])
def test_cors_rejects_other_origins(origin: str) -> None:
    client = TestClient(create_app(deps=make_deps()))
    simple = client.get("/health", headers={"Origin": origin})
    assert "access-control-allow-origin" not in simple.headers
    pre = client.options(
        "/briefings", headers={"Origin": origin, "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in pre.headers


async def test_request_log_has_no_bodies(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="mpa.api")
    body = json.dumps({"message": "very private meeting topic"}).encode()
    app = create_app(run_fn=replay_run(run_events()), deps=make_deps())
    await AsgiCall(app, "POST", "/briefings", body).start().wait_done()
    assert "POST /briefings -> 200" in caplog.text
    assert "private" not in caplog.text

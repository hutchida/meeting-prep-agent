"""Replay keys, record -> replay round trip, misses, redaction and the factory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mpa.contract import LLMMessage, LLMResponse, Settings, ToolSpec, Usage
from mpa.llm import (
    LiteLLMClient,
    RecordingClient,
    RedactionError,
    ReplayClient,
    ReplayMiss,
    build_llm_client,
    request_key,
)
from mpa.llm.replay import check_redacted

MSGS = [LLMMessage(role="system", content="s"), LLMMessage(role="user", content="u")]
TOOLS = [ToolSpec(name="t", description="d", parameters={"type": "object", "properties": {}})]
RESPONSE = LLMResponse(
    message=LLMMessage(role="assistant", content="answer"),
    usage=Usage(prompt_tokens=10, completion_tokens=2, cost_usd=0.0001),
    model="m",
    latency_ms=12,
)


class Inner:
    model = "m"

    def __init__(self, response: LLMResponse = RESPONSE) -> None:
        self.calls = 0
        self.response = response

    async def chat(self, messages: list[LLMMessage], **kw: Any) -> LLMResponse:
        self.calls += 1
        return self.response


def test_key_is_stable_and_ignores_tag_and_dict_order() -> None:
    a = request_key("m", MSGS, TOOLS, 0.0, 100)
    assert a == request_key("m", [m.model_copy() for m in MSGS], list(TOOLS), 0.0, 100)
    assert len(a) == 64
    # pinned: changing the canonical form would invalidate every committed recording
    assert a == request_key("m", MSGS, TOOLS, 0.0, 100)
    assert a != request_key("other", MSGS, TOOLS, 0.0, 100)
    assert a != request_key("m", MSGS, None, 0.0, 100)
    assert a != request_key("m", MSGS, TOOLS, 0.2, 100)
    assert a != request_key("m", MSGS, TOOLS, 0.0, 101)
    assert a != request_key("m", [*MSGS, LLMMessage(role="user", content="more")], TOOLS, 0.0, 100)


def test_key_canonical_form_is_pinned() -> None:
    import hashlib

    expected = json.dumps(
        {
            "max_tokens": None,
            "messages": [{"content": "u", "role": "user"}],
            "model": "m",
            "temperature": 0.0,
            "tools": None,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    key = request_key("m", [LLMMessage(role="user", content="u")], None, 0.0, None)
    assert key == hashlib.sha256(expected.encode()).hexdigest()


async def test_record_then_replay_round_trip(tmp_path: Path) -> None:
    inner = Inner()
    rec = RecordingClient(inner, tmp_path)
    live = await rec.chat(MSGS, tools=TOOLS, max_tokens=100, tag="a:step1")
    files = list(tmp_path.glob("*.json"))  # noqa: ASYNC240
    assert [f.stem for f in files] == [request_key("m", MSGS, TOOLS, 0.0, 100)]
    text = files[0].read_text()
    assert text.endswith("\n") and text.startswith('{\n "request"')
    assert json.loads(text)["request"]["model"] == "m"
    assert set(json.loads(text)) == {"request", "response"}
    assert not list(tmp_path.glob(".rec-*"))  # noqa: ASYNC240

    replay = ReplayClient(tmp_path, 0, model="m")
    again = await replay.chat(MSGS, tools=TOOLS, max_tokens=100, tag="different-tag")
    assert again == live and inner.calls == 1


async def test_replay_miss_carries_hash_and_tag_but_no_prompt(tmp_path: Path) -> None:
    replay = ReplayClient(tmp_path, 0, model="m")
    secret = [LLMMessage(role="user", content="TOP-SECRET-PROMPT-TEXT")]
    with pytest.raises(ReplayMiss) as exc:
        await replay.chat(secret, tag="news:step2")
    assert exc.value.request_hash == request_key("m", secret, None, 0.0, None)
    assert exc.value.tag == "news:step2"
    assert "TOP-SECRET" not in str(exc.value) and "news:step2" in str(exc.value)


async def test_replay_delay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    await RecordingClient(Inner(), tmp_path).chat(MSGS)
    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    monkeypatch.setattr("mpa.llm.replay.asyncio.sleep", fake_sleep)
    await ReplayClient(tmp_path, 250, model="m").chat(MSGS)
    assert slept == [0.25]


async def test_recording_refuses_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LITELLM_BASE_URL", "https://proxy.internal.invalid/v1")
    monkeypatch.setenv("LITELLM_API_KEY", "super-secret-value-1")
    leaky = RESPONSE.model_copy(
        update={
            "message": LLMMessage(role="assistant", content="see https://proxy.internal.invalid/v1")
        }
    )
    with pytest.raises(RedactionError):
        await RecordingClient(Inner(leaky), tmp_path).chat(MSGS)
    assert not list(tmp_path.glob("*"))  # noqa: ASYNC240
    keyed = RESPONSE.model_copy(
        update={"message": LLMMessage(role="assistant", content="key sk-abcdefghijklmnopqrstuvwx")}
    )
    with pytest.raises(RedactionError):
        await RecordingClient(Inner(keyed), tmp_path).chat(MSGS)
    with pytest.raises(RedactionError):
        check_redacted("token super-secret-value-1 here")
    check_redacted("a risk-scoring matrix and https://example.test/news/1 are fine")


def test_factory_modes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LITELLM_BASE_URL", "https://proxy.internal.invalid/v1")
    monkeypatch.setenv("LITELLM_API_KEY", "k-123456")
    base = {"llm_model": "m", "recordings_dir": tmp_path}
    assert isinstance(build_llm_client(Settings(**base, llm_mode="replay")), ReplayClient)  # type: ignore[arg-type]
    assert isinstance(build_llm_client(Settings(**base, llm_mode="live")), LiteLLMClient)  # type: ignore[arg-type]
    recording = build_llm_client(Settings(**base, llm_mode="live", record=True))  # type: ignore[arg-type]
    assert isinstance(recording, RecordingClient)
    assert recording.model == "m"

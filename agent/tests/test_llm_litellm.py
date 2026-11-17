"""LiteLLMClient against httpx.MockTransport: parsing, cost, retries, error redaction."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from mpa.contract import LLMMessage, Settings, ToolCall, ToolSpec
from mpa.llm import LiteLLMClient, LLMConfigError, LLMError
from mpa.llm.pricing import PRICES_PER_MILLION, estimate_cost

BASE = "https://proxy.internal.invalid/v1"
KEY = "sk-test-secret-key-123456"
ENV = {"LITELLM_BASE_URL": BASE, "LITELLM_API_KEY": KEY}
SETTINGS = Settings(llm_model="vertex-ai-gemini-3-flash-preview")
TOOL = ToolSpec(name="get_email", description="d", parameters={"type": "object", "properties": {}})


def ok_body(**message: Any) -> dict[str, Any]:
    return {
        "model": "vertex-ai-gemini-3-flash-preview",
        "choices": [
            {"finish_reason": "stop", "message": {"role": "assistant", "content": "hi", **message}}
        ],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
    }


def client(handler: Any, settings: Settings = SETTINGS) -> tuple[LiteLLMClient, list[float]]:
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    c = LiteLLMClient(settings, env=ENV, transport=httpx.MockTransport(handler), sleep=fake_sleep)
    return c, sleeps


MSGS = [LLMMessage(role="user", content="hello")]


async def test_parses_text_usage_and_header_cost() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok_body(), headers={"x-litellm-response-cost": "0.00123"})

    c, _ = client(handler)
    r = await c.chat(MSGS, max_tokens=500, tag="x:step1")
    assert r.message.content == "hi" and r.message.tool_calls is None
    assert (r.usage.prompt_tokens, r.usage.completion_tokens) == (1000, 200)
    assert r.usage.cost_usd == pytest.approx(0.00123)
    assert r.latency_ms >= 0 and r.finish_reason == "stop"
    assert seen["url"] == f"{BASE}/chat/completions"
    assert seen["auth"] == f"Bearer {KEY}"
    assert seen["body"]["model"] == "vertex-ai-gemini-3-flash-preview"
    assert seen["body"]["max_tokens"] == 500 and seen["body"]["temperature"] == 0.0
    assert "tool_choice" not in seen["body"]
    assert "x:step1" not in json.dumps(seen["body"])


async def test_parses_tool_calls_and_sends_tools() -> None:
    sent: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        calls = [
            {
                "id": "a1",
                "type": "function",
                "function": {"name": "get_email", "arguments": '{"id": "E1"}'},
            },
            {
                "id": "",
                "type": "function",
                "function": {"name": "get_email", "arguments": "not json"},
            },
        ]
        return httpx.Response(200, json=ok_body(content=None, tool_calls=calls))

    c, _ = client(handler)
    history = [
        LLMMessage(role="user", content="q"),
        LLMMessage(
            role="assistant",
            tool_calls=[ToolCall(id="t1", name="get_email", arguments={"id": "E9"})],
        ),
        LLMMessage(role="tool", tool_call_id="t1", name="get_email", content="{}"),
    ]
    r = await c.chat(history, tools=[TOOL])
    assert sent["tool_choice"] == "auto"
    assert sent["tools"][0] == {
        "type": "function",
        "function": {"name": "get_email", "description": "d", "parameters": TOOL.parameters},
    }
    assert sent["messages"][1]["tool_calls"][0]["function"]["arguments"] == '{"id": "E9"}'
    assert sent["messages"][2]["tool_call_id"] == "t1"
    calls = r.message.tool_calls or []
    assert calls[0].arguments == {"id": "E1"}
    assert "_invalid_arguments" in calls[1].arguments and calls[1].id


async def test_cost_falls_back_to_price_table() -> None:
    c, _ = client(lambda req: httpx.Response(200, json=ok_body()))
    r = await c.chat(MSGS)
    assert r.usage.cost_usd == pytest.approx(1000 * 0.5e-6 + 200 * 3.0e-6)
    assert estimate_cost("some-unknown-model", r.usage) == 0.0
    assert "vertex-ai-gemini-3-flash-preview" in PRICES_PER_MILLION


async def test_retries_429_and_5xx_then_succeeds() -> None:
    codes = iter([429, 503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        code = next(codes)
        return httpx.Response(
            code, json=ok_body() if code == 200 else {"error": {"message": "busy"}}
        )

    c, sleeps = client(handler)
    r = await c.chat(MSGS)
    assert r.message.content == "hi"
    assert sleeps == [0.5, 1.0]


async def test_gives_up_after_two_retries_without_leaking_url_or_key() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        leak = {"error": {"message": f"upstream {BASE}/chat/completions rejected Bearer {KEY}"}}
        return httpx.Response(502, json=leak)

    c, _ = client(handler)
    with pytest.raises(LLMError) as exc:
        await c.chat(MSGS)
    assert calls == 3
    text = str(exc.value)
    assert "502" in text
    for secret in (BASE, KEY, "proxy.internal", "Bearer", "sk-"):
        assert secret not in text


async def test_timeouts_and_transport_errors_are_retried_and_redacted() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("timed out talking to " + str(request.url), request=request)
        raise httpx.ConnectError("cannot connect to " + str(request.url), request=request)

    c, _ = client(handler)
    with pytest.raises(LLMError) as exc:
        await c.chat(MSGS)
    assert attempts == 3
    assert BASE not in str(exc.value) and "proxy.internal" not in str(exc.value)
    assert exc.value.__cause__ is None or BASE not in str(exc.value.__cause__)


async def test_client_errors_are_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    c, _ = client(handler)
    with pytest.raises(LLMError, match="HTTP 401"):
        await c.chat(MSGS)
    assert calls == 1


async def test_unsupported_temperature_is_dropped_and_remembered() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "temperature" in body:
            return httpx.Response(
                400, json={"error": {"message": "UnsupportedParamsError: temperature"}}
            )
        return httpx.Response(200, json=ok_body())

    c, _ = client(handler, Settings(llm_model="some-new-model"))
    await c.chat(MSGS)
    await c.chat(MSGS)
    assert ["temperature" in b for b in bodies] == [True, False, False]


async def test_known_models_omit_temperature_up_front() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=ok_body())

    c, _ = client(handler, Settings(llm_model="vertex-ai-claude-sonnet-5"))
    await c.chat(MSGS)
    assert "temperature" not in bodies[0]


async def test_malformed_response_is_an_llm_error() -> None:
    c, _ = client(lambda req: httpx.Response(200, json={"nope": 1}))
    with pytest.raises(LLMError, match="malformed"):
        await c.chat(MSGS)


def test_missing_configuration_names_variables_only() -> None:
    with pytest.raises(LLMConfigError) as exc:
        LiteLLMClient(SETTINGS, env={"LITELLM_BASE_URL": BASE})
    assert "LITELLM_API_KEY" in str(exc.value) and BASE not in str(exc.value)
    with pytest.raises(LLMConfigError) as exc2:
        LiteLLMClient(SETTINGS, env={})
    assert "LITELLM_BASE_URL" in str(exc2.value) and "LITELLM_API_KEY" in str(exc2.value)

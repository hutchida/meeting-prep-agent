"""Chat client for an OpenAI-compatible LiteLLM proxy (httpx, no SDK)."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx

from mpa.contract import LLMMessage, LLMResponse, Settings, ToolCall, ToolSpec, Usage
from mpa.contract.settings import REPO_ROOT
from mpa.llm.errors import LLMConfigError, LLMError
from mpa.llm.pricing import estimate_cost

CALL_TIMEOUT_S = 30.0
MAX_RETRIES = 2
BACKOFF_S = 0.5
_RETRY_STATUS = frozenset({408, 429, 500, 502, 503, 504})
# Models that reject `temperature` (docs/orchestration/measurements.md).
_NO_TEMPERATURE = ("azure/gpt-5", "vertex-ai-claude-sonnet-5", "vertex-ai-claude-opus-4.8")
_OPTIONAL_PARAMS = ("temperature", "reasoning_effort")
_URL_RE = re.compile(r"https?://\S+")
_KEY_RE = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|Bearer\s+\S+)")

Sleep = Callable[[float], Awaitable[None]]


def read_connection_env(env: Mapping[str, str] | None = None) -> tuple[str, str]:
    """Return (base_url, api_key); the error names missing variables only."""
    if env is None:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env", override=False)
        env = os.environ
    base = (env.get("LITELLM_BASE_URL") or "").strip()
    key = (env.get("LITELLM_API_KEY") or "").strip()
    missing = [n for n, v in (("LITELLM_BASE_URL", base), ("LITELLM_API_KEY", key)) if not v]
    if missing:
        raise LLMConfigError(
            f"live mode needs {' and '.join(missing)} to be set in the environment"
        )
    return base.rstrip("/"), key


def _wire_message(m: LLMMessage) -> dict[str, Any]:
    out: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        out["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
            }
            for c in m.tool_calls
        ]
    if m.role == "tool":
        out["tool_call_id"] = m.tool_call_id
        if m.name:
            out["name"] = m.name
    return out


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if raw in (None, ""):
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {"_invalid_arguments": str(raw)[:500]}
    return parsed if isinstance(parsed, dict) else {"_invalid_arguments": str(raw)[:500]}


class LiteLLMClient:
    def __init__(
        self,
        settings: Settings,
        *,
        env: Mapping[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        timeout_s: float = CALL_TIMEOUT_S,
    ) -> None:
        self._base_url, self._api_key = read_connection_env(env)
        self.model = settings.llm_model
        self._sleep = sleep
        self._http = httpx.AsyncClient(transport=transport, timeout=timeout_s)
        self._dropped: set[str] = set()
        if self.model.startswith(_NO_TEMPERATURE):
            self._dropped.add("temperature")

    async def aclose(self) -> None:
        await self._http.aclose()

    def _safe(self, text: str) -> str:
        for secret in (self._base_url, self._api_key):
            text = text.replace(secret, "[redacted]")
        return _KEY_RE.sub("[redacted]", _URL_RE.sub("[url]", text))[:200]

    def _payload(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSpec] | None,
        temperature: float,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [_wire_message(m) for m in messages],
            "temperature": temperature,
        }
        if "gemini-3" in self.model:
            body["reasoning_effort"] = "minimal"
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
            body["tool_choice"] = "auto"
        for name in self._dropped:
            body.pop(name, None)
        return body

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tag: str | None = None,
    ) -> LLMResponse:
        url = f"{self._base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        attempt = 0
        while True:
            body = self._payload(messages, tools, temperature, max_tokens)
            started = time.perf_counter()
            error: LLMError
            try:
                resp = await self._http.post(url, json=body, headers=headers)
            except httpx.TimeoutException:
                error = LLMError("model call timed out", retryable=True)
            except httpx.HTTPError as exc:
                error = LLMError(f"model call failed: {type(exc).__name__}", retryable=True)
            else:
                latency_ms = round((time.perf_counter() - started) * 1000)
                if resp.status_code == 200:
                    return self._parse(resp, latency_ms)
                if resp.status_code == 400 and self._drop_unsupported(resp, body):
                    continue
                error = LLMError(
                    f"model call failed: HTTP {resp.status_code} {self._error_text(resp)}".strip(),
                    status=resp.status_code,
                    retryable=resp.status_code in _RETRY_STATUS,
                )
            if not error.retryable or attempt >= MAX_RETRIES:
                raise error
            await self._sleep(BACKOFF_S * (2**attempt))
            attempt += 1

    def _error_text(self, resp: httpx.Response) -> str:
        try:
            data = resp.json()
            msg = (
                data["error"]["message"]
                if isinstance(data.get("error"), dict)
                else data.get("error")
            )
            return self._safe(str(msg or ""))
        except (ValueError, KeyError, TypeError, AttributeError):
            return ""

    def _drop_unsupported(self, resp: httpx.Response, body: dict[str, Any]) -> bool:
        text = resp.text.lower()
        for name in _OPTIONAL_PARAMS:
            if name in body and name in text:
                self._dropped.add(name)
                return True
        return False

    def _parse(self, resp: httpx.Response, latency_ms: int) -> LLMResponse:
        try:
            data = resp.json()
            choice = data["choices"][0]
            msg = choice["message"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError("model returned a malformed response") from None
        calls = [
            ToolCall(
                id=str(c.get("id") or f"call_{i}"),
                name=str(c["function"]["name"]),
                arguments=_parse_arguments(c["function"].get("arguments")),
            )
            for i, c in enumerate(msg.get("tool_calls") or [])
        ]
        raw_usage = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(raw_usage.get("prompt_tokens") or 0),
            completion_tokens=int(raw_usage.get("completion_tokens") or 0),
        )
        header = resp.headers.get("x-litellm-response-cost")
        try:
            usage.cost_usd = (
                float(header) if header is not None else estimate_cost(self.model, usage)
            )
        except ValueError:
            usage.cost_usd = estimate_cost(self.model, usage)
        return LLMResponse(
            message=LLMMessage(
                role="assistant", content=msg.get("content") or None, tool_calls=calls or None
            ),
            usage=usage,
            model=str(data.get("model") or self.model),
            finish_reason=choice.get("finish_reason"),
            latency_ms=latency_ms,
        )

"""Record and replay of LLM calls, keyed by a hash of the request."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mpa.contract import DEFAULT_LLM_MODEL, LLMClient, LLMMessage, LLMResponse, ToolSpec
from mpa.llm.errors import RedactionError, ReplayMiss

_SECRET_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._~+/=-]{8,}")


def request_dict(
    model: str,
    messages: list[LLMMessage],
    tools: list[ToolSpec] | None,
    temperature: float,
    max_tokens: int | None,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [m.model_dump(mode="json", exclude_none=True) for m in messages],
        "tools": [t.model_dump(mode="json") for t in tools] if tools else None,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def request_key(
    model: str,
    messages: list[LLMMessage],
    tools: list[ToolSpec] | None,
    temperature: float,
    max_tokens: int | None,
) -> str:
    """SHA-256 of the canonical JSON of the request; `tag` is deliberately not part of it."""
    payload = canonical_json(request_dict(model, messages, tools, temperature, max_tokens))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ReplayClient:
    def __init__(
        self,
        recordings_dir: Path,
        delay_ms: int = 250,
        *,
        model: str = DEFAULT_LLM_MODEL,
    ) -> None:
        self._dir = Path(recordings_dir)
        self._delay = max(0, delay_ms) / 1000
        self.model = model

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tag: str | None = None,
    ) -> LLMResponse:
        key = request_key(self.model, messages, tools, temperature, max_tokens)
        path = self._dir / f"{key}.json"
        if not path.is_file():
            raise ReplayMiss(key, tag)
        if self._delay:
            await asyncio.sleep(self._delay)
        stored = json.loads(path.read_text(encoding="utf-8"))
        return LLMResponse.model_validate(stored["response"])


def check_redacted(text: str, env: Mapping[str, str] | None = None) -> None:
    """Raise RedactionError if `text` holds the proxy URL, the key or a key-shaped string."""
    env = os.environ if env is None else env
    for name in ("LITELLM_BASE_URL", "LITELLM_API_KEY"):
        value = (env.get(name) or "").strip()
        if len(value) >= 6 and value in text:
            raise RedactionError(f"recording refused: it contains the value of {name}")
    if _SECRET_RE.search(text):
        raise RedactionError("recording refused: it contains a key-shaped string")


class RecordingClient:
    def __init__(self, inner: LLMClient, recordings_dir: Path, *, model: str | None = None) -> None:
        self._inner = inner
        self._dir = Path(recordings_dir)
        self.model = model or str(getattr(inner, "model", DEFAULT_LLM_MODEL))

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tag: str | None = None,
    ) -> LLMResponse:
        response = await self._inner.chat(
            messages, tools=tools, temperature=temperature, max_tokens=max_tokens, tag=tag
        )
        key = request_key(self.model, messages, tools, temperature, max_tokens)
        record = {
            "request": request_dict(self.model, messages, tools, temperature, max_tokens),
            "response": response.model_dump(mode="json", exclude_none=True),
        }
        text = json.dumps(record, sort_keys=True, indent=1, ensure_ascii=False) + "\n"
        check_redacted(text)
        self._write(self._dir / f"{key}.json", text)
        return response

    @staticmethod
    def _write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".rec-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

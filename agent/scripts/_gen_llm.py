"""Cached LLM prose for the data generator.

Requests go to the LiteLLM proxy (OpenAI-compatible, plain httpx). Every response is cached by
a hash of the request content under data/_gen_cache/, so a run without network or key replays
byte-identically. Neither the proxy URL, headers nor keys are ever written to the cache.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import httpx

SEED = 20260309
PROMPT_VERSION = "v2"
MAX_TOKENS = 3000


class CacheMiss(RuntimeError):
    pass


def request_hash(messages: list[dict[str, str]]) -> str:
    payload = {
        "v": PROMPT_VERSION,
        "messages": messages,
        "temperature": 0,
        "seed": SEED,
        "max_tokens": MAX_TOKENS,
        "reasoning_effort": "minimal",
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class LLMCache:
    def __init__(self, path: Path, offline: bool) -> None:
        self.path = path
        self.offline = offline
        self.entries: dict[str, dict[str, Any]] = {}
        self.dirty = False
        self.hits = 0
        self.misses = 0
        self.cost_usd = 0.0
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                entry = json.loads(line)
                self.entries[entry["hash"]] = entry
        self._client: httpx.Client | None = None
        self._lock = threading.Lock()

    def _http(self) -> tuple[httpx.Client, str, str]:
        base = os.environ.get("LITELLM_BASE_URL", "").rstrip("/")
        key = os.environ.get("LITELLM_API_KEY", "")
        model = os.environ.get("LLM_MODEL", "")
        if not (base and key and model):
            raise CacheMiss("cache miss and LITELLM_BASE_URL/LITELLM_API_KEY/LLM_MODEL are not set")
        if self._client is None:
            self._client = httpx.Client(
                base_url=base, headers={"Authorization": f"Bearer {key}"}, timeout=180
            )
        return self._client, base, model

    def complete(self, messages: list[dict[str, str]]) -> str:
        digest = request_hash(messages)
        with self._lock:
            cached = self.entries.get(digest)
        if cached is not None:
            self.hits += 1
            return str(cached["content"])
        if self.offline:
            raise CacheMiss(f"offline cache miss for request {digest[:12]}")
        client, _base, model = self._http()
        body = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "seed": SEED,
            "max_tokens": MAX_TOKENS,
            "reasoning_effort": "minimal",
        }
        last = ""
        for attempt in range(4):
            try:
                resp = client.post("/chat/completions", json=body)
                if resp.status_code == 200:
                    break
                last = f"HTTP {resp.status_code}"
                if resp.status_code == 400 and "reasoning_effort" in body:
                    del body["reasoning_effort"]
                    continue
            except httpx.HTTPError as exc:
                last = type(exc).__name__
            time.sleep(2**attempt)
        else:
            raise RuntimeError(f"LLM request failed: {last}")
        data = resp.json()
        content = (data["choices"][0]["message"].get("content") or "").strip()
        if not content or data["choices"][0].get("finish_reason") == "length":
            raise RuntimeError("LLM returned empty or truncated content")
        try:
            self.cost_usd += float(resp.headers.get("x-litellm-response-cost", "0"))
        except ValueError:
            pass
        usage = data.get("usage", {})
        with self._lock:
            self.misses += 1
            self.dirty = True
            self.entries[digest] = {
                "hash": digest,
                "model": model,
                "content": content,
                "tokens_in": usage.get("prompt_tokens"),
                "tokens_out": usage.get("completion_tokens"),
            }
            self.save()
        return content

    def save(self) -> None:
        if not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(self.entries[h], sort_keys=True, ensure_ascii=False)
            for h in sorted(self.entries)
        ]
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.dirty = False


_URL = re.compile(r"https?://[^\s)>\]]+")
_ADDR = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def sanitize(text: str) -> str:
    """Keep every generated URL and address inside the reserved .test domain space."""
    text = _URL.sub(
        lambda m: m.group(0) if "example.test" in m.group(0) else "https://example.test/link", text
    )
    text = _ADDR.sub(
        lambda m: m.group(0) if m.group(0).endswith(".test") else "someone@example.test", text
    )
    return text.replace("\r\n", "\n").strip()

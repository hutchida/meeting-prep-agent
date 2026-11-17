"""Helpers for API tests: a raw ASGI driver (httpx buffers streams), fixtures and fakes."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from mpa.contract import AgentEvent, BriefingRequest, NoopTracer, RunDeps, Settings

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "packages" / "contract" / "fixtures"


def run_events(name: str = "run.brightmoor.normal") -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads((FIXTURES / "runs" / f"{name}.events.json").read_text())
    return data


def fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return data


class Untouchable:
    """Stands in for the LLM and data source: any use fails the test."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"unexpected use of {name}")


def make_deps(data: Any = None, tracer: Any = None) -> RunDeps:
    return RunDeps(
        llm=Untouchable(),
        data=data if data is not None else Untouchable(),
        tracer=tracer if tracer is not None else NoopTracer(),
        settings=Settings(llm_model="test-model"),
    )


def replay_run(events: list[dict[str, Any]]) -> Any:
    async def run(request: BriefingRequest, deps: RunDeps) -> AsyncIterator[AgentEvent]:
        for event in events:
            yield AgentEvent.model_validate(event)

    return run


def parse_sse(raw: bytes) -> list[dict[str, Any]]:
    """Messages as {"event", "data"} (data parsed) plus {"comment"} entries, in order."""
    out: list[dict[str, Any]] = []
    for block in raw.decode().split("\n\n"):
        if not block:
            continue
        if block.startswith(":"):
            out.append({"comment": block[1:].strip()})
            continue
        lines = block.split("\n")
        assert lines[0].startswith("event: ") and lines[1].startswith("data: "), block
        assert len(lines) == 2, "one event and one data line per message"
        out.append({"event": lines[0][7:], "data": json.loads(lines[1][6:]), "raw": lines[1][6:]})
    return out


class AsgiCall:
    """Runs one HTTP request against an ASGI app, exposing body chunks as they are sent."""

    def __init__(
        self,
        app: Any,
        method: str,
        path: str,
        body: bytes = b"",
        *,
        spec_version: str = "2.3",
    ) -> None:
        self.app = app
        self.chunks: list[tuple[float, bytes]] = []
        self.status: int | None = None
        self.headers: dict[str, str] = {}
        self.finished = asyncio.Event()
        self.disconnected = asyncio.Event()
        self._new_chunk = asyncio.Event()
        self._sent_body = False
        self._spec_version = spec_version
        self.started_at = time.monotonic()
        self.scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": spec_version},
            "http_version": "1.1",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
            "client": ("127.0.0.1", 1),
            "server": ("testserver", 80),
            "scheme": "http",
            "root_path": "",
        }
        self._body = body
        self.task: asyncio.Task[None] | None = None
        self.error: BaseException | None = None

    def start(self) -> AsgiCall:
        self.task = asyncio.create_task(self._run())
        return self

    async def _receive(self) -> dict[str, Any]:
        if not self._sent_body:
            self._sent_body = True
            return {"type": "http.request", "body": self._body, "more_body": False}
        await self.disconnected.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            self.status = message["status"]
            self.headers = {k.decode().lower(): v.decode() for k, v in message["headers"]}
            return
        if self.disconnected.is_set() and self._spec_version >= "2.4":
            raise OSError("client disconnected")
        body = message.get("body", b"")
        if body:
            self.chunks.append((time.monotonic() - self.started_at, body))
            self._new_chunk.set()
        if not message.get("more_body", False):
            self.finished.set()

    async def _run(self) -> None:
        try:
            await self.app(self.scope, self._receive, self._send)
        except BaseException as exc:
            self.error = exc
        finally:
            self.finished.set()
            self._new_chunk.set()

    @property
    def body(self) -> bytes:
        return b"".join(chunk for _, chunk in self.chunks)

    async def wait_for_chunks(self, count: int, within: float = 5.0) -> None:
        deadline = time.monotonic() + within
        while len(self.chunks) < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or self.finished.is_set():
                break
            self._new_chunk.clear()
            try:
                await asyncio.wait_for(self._new_chunk.wait(), remaining)
            except TimeoutError:
                break

    async def wait_done(self, within: float = 10.0) -> bytes:
        assert self.task is not None
        await asyncio.wait_for(self.task, within)
        return self.body

    def disconnect(self) -> None:
        self.disconnected.set()

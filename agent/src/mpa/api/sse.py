"""Server-sent events for a briefing run."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import time
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from mpa.contract import LIMITS, AgentEvent, BriefingRequest, RunDeps
from mpa.contract.assemble import SECTION_IDS, SECTION_TITLES

logger = logging.getLogger("mpa.api")

KEEPALIVE_S = 10.0
QUEUE_SIZE = 64
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

STREAM_OPEN = b": stream-open\n\n"
KEEP_ALIVE = b": keep-alive\n\n"


class _End:
    pass


class _Failed:
    def __init__(self, reason: str) -> None:
        self.reason = reason


class SSEResponse(StreamingResponse):
    """StreamingResponse that notices a client disconnect at once, even while the run is idle.

    Starlette only notices on the next write for ASGI spec >= 2.4, which could be a keep-alive
    ten seconds away. The generator is always closed so the run is cancelled.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def watch_disconnect() -> None:
            while (await receive())["type"] != "http.disconnect":
                pass

        stream = asyncio.create_task(self.stream_response(send), name="sse-stream")
        watcher = asyncio.create_task(watch_disconnect(), name="sse-disconnect")
        try:
            await asyncio.wait({stream, watcher}, return_when=asyncio.FIRST_COMPLETED)
            if stream.done() and not stream.cancelled():
                try:
                    stream.result()
                except OSError:
                    return
        finally:
            for task in (stream, watcher):
                task.cancel()
            await asyncio.gather(stream, watcher, return_exceptions=True)
            aclose = getattr(self.body_iterator, "aclose", None)
            if aclose is not None:
                with contextlib.suppress(Exception):
                    await aclose()


def frame(event: AgentEvent) -> bytes:
    """One SSE message. Raises ValueError if the event is over the contract size limit."""
    data = event.model_dump_json(exclude_none=True)
    if len(data.encode("utf-8")) > LIMITS["AGENT_EVENT_MAX_BYTES"]:
        raise ValueError("event over size limit")
    return f"event: {event.root.type}\ndata: {data}\n\n".encode()


def _to_event(item: Any) -> AgentEvent:
    plain = item.model_dump(mode="json", exclude_none=True) if isinstance(item, BaseModel) else item
    return AgentEvent.model_validate(plain)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


class _RunState:
    """Tracks what has been sent so a safe terminal event can be built on any failure."""

    def __init__(self, deps: RunDeps) -> None:
        self.started = time.monotonic()
        self.default_ts = _iso(deps.settings.demo_now)
        self.run_id = "run_unknown"
        self.last_ts = self.default_ts
        self.next_seq = 0
        self.steps = 0
        self.open_agents: list[str] = []
        self.planned = False
        self.verified = False
        self.drafted: set[str] = set()

    def observe(self, event: AgentEvent) -> None:
        root = event.root
        self.run_id = root.run_id
        self.last_ts = root.ts
        self.next_seq = root.seq + 1
        if root.type == "tool_call":
            self.steps += 1
        elif root.type == "plan":
            self.planned = True
        elif root.type == "verifier_result":
            self.verified = True
        elif root.type == "draft":
            self.drafted.update(section.id for section in root.sections)
        elif root.type == "subagent_started":
            if root.agent not in self.open_agents:
                self.open_agents.append(root.agent)
        elif root.type in ("subagent_done", "subagent_failed") and root.agent in self.open_agents:
            self.open_agents.remove(root.agent)

    def terminal_frames(self) -> list[bytes]:
        frames: list[bytes] = []
        for agent in self.open_agents:
            frames.append(
                frame(
                    self._build(
                        {
                            "type": "subagent_failed",
                            "agent": agent,
                            "reason": "error",
                            "error": "internal error",
                        }
                    )
                )
            )
        missing = [i for i in SECTION_IDS if i not in self.drafted] if self.planned else []
        if missing and not self.verified and not self.drafted:
            counts = {"sentences_total": 0, "sentences_kept": 0, "sentences_dropped": 0}
            verifier = {"type": "verifier_result", "verifier": counts, "dropped": []}
            frames.append(frame(self._build(verifier)))
        for index, section_id in enumerate(missing):
            section = {
                "id": section_id,
                "title": SECTION_TITLES[section_id],
                "sentences": [],
                "empty": True,
            }
            draft = {
                "type": "draft",
                "sections": [section],
                "complete": index == len(missing) - 1,
            }
            frames.append(frame(self._build(draft)))
        stats = {
            "steps": self.steps,
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0,
            "duration_ms": int((time.monotonic() - self.started) * 1000),
        }
        frames.append(frame(self._build({"type": "run_done", "partial": True, "stats": stats})))
        return frames

    def _build(self, body: dict[str, Any]) -> AgentEvent:
        event = AgentEvent.model_validate(
            {"run_id": self.run_id, "seq": self.next_seq, "ts": self.last_ts, **body}
        )
        self.next_seq += 1
        return event


async def stream_briefing(
    run_fn: Callable[[BriefingRequest, RunDeps], Any],
    request: BriefingRequest,
    deps: RunDeps,
    *,
    keepalive_s: float = KEEPALIVE_S,
) -> AsyncIterator[bytes]:
    queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=QUEUE_SIZE)
    state = _RunState(deps)

    async def produce() -> None:
        try:
            source = run_fn(request, deps)
            if inspect.isawaitable(source):
                source = await source
            try:
                async for item in source:
                    await queue.put(item)
            finally:
                aclose = getattr(source, "aclose", None)
                if aclose is not None:
                    await aclose()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("run failed: %s", type(exc).__name__)
            await queue.put(_Failed(type(exc).__name__))
        else:
            await queue.put(_End())

    yield STREAM_OPEN
    producer = asyncio.create_task(produce(), name="briefing-run")
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), keepalive_s)
            except TimeoutError:
                yield KEEP_ALIVE
                continue
            if isinstance(item, _End | _Failed):
                for out in state.terminal_frames():
                    yield out
                return
            try:
                event = _to_event(item)
                out = frame(event)
            except Exception as exc:
                logger.warning("invalid event from run: %s", type(exc).__name__)
                for out in state.terminal_frames():
                    yield out
                return
            state.observe(event)
            yield out
            if event.root.type == "run_done":
                return
    finally:
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
        _flush_tracer(deps)


def _flush_tracer(deps: RunDeps) -> None:
    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _safe_flush, deps.tracer.flush)
    except Exception:
        return


def _safe_flush(flush: Callable[[], object]) -> None:
    try:
        flush()
    except Exception as exc:
        logger.debug("tracer flush failed: %s", type(exc).__name__)

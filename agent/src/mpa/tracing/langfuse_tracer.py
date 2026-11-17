"""Langfuse-backed tracer (Langfuse Python SDK 2.x, self-hosted server 2.x).

The SDK queues events and ships them from background threads, so span calls only enqueue.
Everything here swallows exceptions: tracing must never break or slow a run.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from mpa.contract import NullSpan, Span, Usage
from mpa.tracing.redact import sanitize, secret_values

logger = logging.getLogger("mpa.tracing")

MAX_CONSECUTIVE_FAILURES = 5
FLUSH_TIMEOUT_S = 5.0
MAX_ERROR_CHARS = 300

_NULL: Span = NullSpan()


class _LangfuseSpan:
    def __init__(
        self,
        tracer: LangfuseTracer,
        obj: Any,
        *,
        root: bool,
        metadata: dict[str, Any],
    ) -> None:
        self._tracer = tracer
        self.obj = obj
        self._root = root
        self._metadata = metadata
        self._ended = False

    def set(self, **attrs: Any) -> None:
        self._tracer._guard(lambda: self._set(attrs), None)

    def end(self, *, error: str | None = None) -> None:
        self._tracer._guard(lambda: self._end(error), None)

    def _set(self, attrs: dict[str, Any]) -> None:
        if self._ended or not attrs:
            return
        tracer = self._tracer
        fields: dict[str, Any] = {}
        for key, value in attrs.items():
            if key in ("output", "input"):
                fields[key] = tracer._clean(value)
            elif key in ("level", "status_message") and not self._root:
                fields[key] = tracer._clean(value, max_chars=MAX_ERROR_CHARS)
            elif key in ("model", "version"):
                fields[key] = tracer._clean(value, max_chars=200)
            else:
                self._metadata[key] = tracer._clean(value, max_chars=1000)
        fields["metadata"] = dict(self._metadata)
        self.obj.update(**fields)

    def _end(self, error: str | None) -> None:
        if self._ended:
            return
        self._ended = True
        tracer = self._tracer
        message = tracer._clean(error, max_chars=MAX_ERROR_CHARS) if error else None
        if self._root:
            fields: dict[str, Any] = {"metadata": dict(self._metadata)}
            if message:
                fields["metadata"] = {**self._metadata, "error": message}
                fields["tags"] = ["error"]
            self.obj.update(**fields)
            return
        fields = {"end_time": datetime.now(UTC), "metadata": dict(self._metadata)}
        if message:
            fields["level"] = "ERROR"
            fields["status_message"] = message
        self.obj.end(**fields)


class LangfuseTracer:
    """Implements `Tracer`: one trace per run, nested spans, generations for LLM calls."""

    def __init__(self, client: Any, *, secrets: tuple[str, ...] | None = None) -> None:
        self._client = client
        self._secrets = secret_values() if secrets is None else secrets
        self._failures = 0
        self._disabled = False
        self._lock = threading.Lock()

    def start_run(self, run_id: str, *, name: str, input: dict[str, Any]) -> Span:
        def make() -> Span:
            trace = self._client.trace(id=run_id, name=name, input=self._clean(input))
            return _LangfuseSpan(self, trace, root=True, metadata={})

        return self._guard(make, _NULL)

    def start_span(
        self,
        parent: Span,
        name: str,
        *,
        kind: Literal["agent", "step", "tool", "llm"],
        input: Any = None,
    ) -> Span:
        if not isinstance(parent, _LangfuseSpan):
            return NullSpan()

        def make() -> Span:
            create = parent.obj.generation if kind == "llm" else parent.obj.span
            obj = create(
                name=self._clean(name, max_chars=200),
                input=self._clean(input),
                metadata={"kind": kind},
                start_time=datetime.now(UTC),
            )
            return _LangfuseSpan(self, obj, root=False, metadata={"kind": kind})

        return self._guard(make, _NULL)

    def record_llm(
        self, parent: Span, *, model: str, input: Any, output: Any, usage: Usage, latency_ms: int
    ) -> None:
        if not isinstance(parent, _LangfuseSpan):
            return

        def record() -> None:
            end = datetime.now(UTC)
            parent.obj.generation(
                name=self._clean(model, max_chars=200),
                model=self._clean(model, max_chars=200),
                input=self._clean(input),
                output=self._clean(output),
                usage={
                    "input": usage.prompt_tokens,
                    "output": usage.completion_tokens,
                    "total": usage.prompt_tokens + usage.completion_tokens,
                    "unit": "TOKENS",
                    "total_cost": usage.cost_usd,
                },
                metadata={"latency_ms": latency_ms},
                start_time=end - timedelta(milliseconds=max(latency_ms, 0)),
                end_time=end,
            )

        self._guard(record, None)

    def flush(self) -> None:
        if self._disabled:
            return
        worker = threading.Thread(
            target=self._flush_quietly, name="mpa-langfuse-flush", daemon=True
        )
        try:
            worker.start()
            worker.join(FLUSH_TIMEOUT_S)
        except Exception:
            return

    def _flush_quietly(self) -> None:
        self._guard(self._client.flush, None)

    def _clean(self, value: Any, *, max_chars: int = 4000) -> Any:
        return sanitize(value, secrets=self._secrets, max_chars=max_chars)

    def _guard[T](self, fn: Callable[[], T], default: T) -> T:
        if self._disabled:
            return default
        try:
            result = fn()
        except Exception as exc:
            with self._lock:
                self._failures += 1
                trip = self._failures >= MAX_CONSECUTIVE_FAILURES and not self._disabled
                if trip:
                    self._disabled = True
            logger.debug("tracing call failed: %s", type(exc).__name__)
            if trip:
                logger.warning("Langfuse tracing disabled after repeated errors")
            return default
        self._failures = 0
        return result

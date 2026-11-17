"""Tracing: `build_tracer(settings)` returns a no-op tracer or the optional Langfuse tracer."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from mpa.contract import NoopTracer, Settings, Tracer
from mpa.tracing.langfuse_tracer import LangfuseTracer
from mpa.tracing.redact import secret_values

__all__ = ["LangfuseTracer", "build_tracer"]

logger = logging.getLogger("mpa.tracing")

PROBE_TIMEOUT_S = 2.0


def _probe_host(host: str) -> bool:
    try:
        response = httpx.get(f"{host}/api/public/health", timeout=PROBE_TIMEOUT_S)
    except Exception:
        return False
    return response.status_code < 500


def _make_client(public_key: str, secret_key: str, host: str) -> Any:
    from langfuse import Langfuse  # type: ignore[import-not-found,unused-ignore]

    return Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        host=host,
        flush_at=20,
        flush_interval=1.0,
        max_retries=1,
        timeout=5,
    )


def _package_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("langfuse") is not None


def build_tracer(
    settings: Settings,
    *,
    env: Mapping[str, str] | None = None,
    client_factory: Callable[[str, str, str], Any] | None = None,
    probe: Callable[[str], bool] | None = None,
) -> Tracer:
    """`off` -> NoopTracer. `langfuse` -> LangfuseTracer, or NoopTracer plus one warning.

    The warning names the reason only, never the host or keys.
    """
    if settings.tracing != "langfuse":
        return NoopTracer()
    source: Mapping[str, str] = os.environ if env is None else env
    public_key = source.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = source.get("LANGFUSE_SECRET_KEY", "").strip()
    host = source.get("LANGFUSE_HOST", "").strip().rstrip("/")

    reason: str | None = None
    if not public_key or not secret_key:
        reason = "keys_missing"
    elif not host.startswith(("http://", "https://")):
        reason = "host_missing"
    elif client_factory is None and not _package_available():
        reason = "package_missing"
    elif not (probe or _probe_host)(host):
        reason = "unreachable"

    client: Any = None
    if reason is None:
        try:
            client = (client_factory or _make_client)(public_key, secret_key, host)
        except Exception as exc:
            reason = f"init_failed ({type(exc).__name__})"
    if reason is not None or client is None:
        logger.warning("Langfuse tracing disabled: %s; using the no-op tracer", reason)
        return NoopTracer()
    secrets = secret_values({k: v for k, v in source.items()})
    return LangfuseTracer(client, secrets=secrets)

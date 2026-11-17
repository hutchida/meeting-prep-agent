"""FastAPI app: GET /health, POST /briefings (SSE), GET /sources/{type}/{id}."""

from __future__ import annotations

import logging
import re
import time
from importlib import metadata
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from mpa.api.deps import DepsProvider, RunFn, ServiceUnavailable, resolve_default_run_fn
from mpa.api.sse import KEEPALIVE_S, SSE_HEADERS, SSEResponse, stream_briefing
from mpa.contract import BriefingRequest, DataSourceError, RunDeps, SourceItem
from mpa.contract.citations import ID_PREFIX

logger = logging.getLogger("mpa.api")

CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]
SourceType = Literal["email", "chat", "doc", "news", "contact", "cal"]
_ID_PATTERNS = {kind: re.compile(rf"{prefix}[0-9]{{1,9}}") for kind, prefix in ID_PREFIX.items()}


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status)


class RequestLogMiddleware:
    """Logs method, path, status and duration. Never bodies, queries, headers or env values."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.monotonic()
        status = 0

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            logger.info(
                "%s %s -> %s (%d ms)",
                scope.get("method"),
                scope.get("path"),
                status or "-",
                int((time.monotonic() - started) * 1000),
            )


def _version() -> str:
    try:
        return metadata.version("mpa")
    except metadata.PackageNotFoundError:
        return "0.0.0"


def create_app(
    run_fn: RunFn | None = None,
    deps: RunDeps | None = None,
    *,
    keepalive_s: float = KEEPALIVE_S,
) -> FastAPI:
    app = FastAPI(title="meeting-prep-agent", version=_version())
    provider = DepsProvider(deps)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
    )
    app.add_middleware(RequestLogMiddleware)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        problems = [
            {"loc": list(e.get("loc", ())), "msg": str(e.get("msg", "")), "type": e.get("type")}
            for e in exc.errors()
        ]
        return JSONResponse(
            {"error": "validation_error", "detail": jsonable_encoder(problems)}, status_code=422
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        settings = provider.peek_settings()
        run_deps = provider.peek_deps()
        tracing = settings.tracing if settings else "unknown"
        if run_deps is not None and type(run_deps.tracer).__name__ == "NoopTracer":
            tracing = "off"
        return {
            "status": "ok",
            "version": _version(),
            "llm_mode": settings.llm_mode if settings else "unknown",
            "data_source": settings.data_source if settings else "unknown",
            "tracing": tracing,
        }

    @app.post("/briefings", response_model=None)
    async def briefings(request: BriefingRequest) -> Response:
        try:
            fn = run_fn or resolve_default_run_fn()
            run_deps = await provider.run_deps()
        except ServiceUnavailable:
            return _error(503, "service_unavailable")
        return SSEResponse(
            stream_briefing(fn, request, run_deps, keepalive_s=keepalive_s),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    @app.get("/sources/{type}/{id}", response_model=None)
    async def source(type: SourceType, id: str) -> Response:
        if not _ID_PATTERNS[type].fullmatch(id):
            return _error(422, "invalid_id")
        try:
            data = await provider.data()
        except ServiceUnavailable:
            return _error(503, "service_unavailable")
        try:
            item: Any = SourceItem.model_validate(
                _plain(await data.get_source(type, id))
            ).model_dump(mode="json", exclude_none=True)
        except KeyError:
            return _error(404, "not_found")
        except (DataSourceError, NotImplementedError):
            return _error(503, "service_unavailable")
        except Exception as exc:
            logger.warning("source lookup failed: %s", exc.__class__.__name__)
            return _error(500, "internal_error")
        return JSONResponse(item)

    return app


def _plain(item: Any) -> Any:
    dump = getattr(item, "model_dump", None)
    return dump(mode="json", exclude_none=True) if dump else item


app = create_app()

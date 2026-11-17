"""Lazy, failure-tolerant construction of run dependencies."""

from __future__ import annotations

import asyncio
import importlib
import logging
import threading
from collections.abc import AsyncIterator, Callable
from typing import Any

from mpa.contract import AgentEvent, BriefingRequest, DataSource, RunDeps, Settings

logger = logging.getLogger("mpa.api")

RunFn = Callable[[BriefingRequest, RunDeps], AsyncIterator[AgentEvent]]


class ServiceUnavailable(Exception):
    """A dependency of this route could not be built. Carries no detail on purpose."""


def resolve_default_run_fn() -> RunFn:
    try:
        module = importlib.import_module("mpa.agents.orchestrator")
        run_fn: RunFn = module.run_briefing
    except (ImportError, AttributeError) as exc:
        logger.warning("run_briefing unavailable: %s", type(exc).__name__)
        raise ServiceUnavailable from None
    return run_fn


class DepsProvider:
    """Builds `Settings`, the data source and `RunDeps` on first use, each at most once."""

    def __init__(self, deps: RunDeps | None = None) -> None:
        self._deps = deps
        self._settings: Settings | None = deps.settings if deps else None
        self._data: DataSource | None = deps.data if deps else None
        self._lock = threading.RLock()

    def peek_settings(self) -> Settings | None:
        if self._settings is None:
            try:
                self._settings = Settings.from_env()
            except Exception as exc:
                logger.warning("settings unavailable: %s", type(exc).__name__)
                return None
        return self._settings

    def peek_deps(self) -> RunDeps | None:
        return self._deps

    async def data(self) -> DataSource:
        if self._data is None:
            self._data = await asyncio.to_thread(self._build_data)
        return self._data

    async def run_deps(self) -> RunDeps:
        if self._deps is None:
            self._deps = await asyncio.to_thread(self._build_run_deps)
        return self._deps

    def _require_settings(self) -> Settings:
        settings = self.peek_settings()
        if settings is None:
            raise ServiceUnavailable
        return settings

    def _build_data(self) -> DataSource:
        with self._lock:
            if self._data is not None:
                return self._data
            settings = self._require_settings()
            try:
                from mpa.data import build_data_source  # type: ignore[attr-defined]

                data: DataSource = build_data_source(settings)
            except Exception as exc:
                logger.warning("data source unavailable: %s", type(exc).__name__)
                raise ServiceUnavailable from None
            return data

    def _build_run_deps(self) -> RunDeps:
        with self._lock:
            if self._deps is not None:
                return self._deps
            settings = self._require_settings()
            data = self._build_data()
            try:
                from mpa.llm import build_llm_client  # type: ignore[attr-defined]
                from mpa.tracing import build_tracer

                llm: Any = build_llm_client(settings)
                tracer = build_tracer(settings)
            except Exception as exc:
                logger.warning("run dependencies unavailable: %s", type(exc).__name__)
                raise ServiceUnavailable from None
            return RunDeps(llm=llm, data=data, tracer=tracer, settings=settings)

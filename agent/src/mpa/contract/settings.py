"""Run settings, read from the environment (and `.env` via python-dotenv)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

REPO_ROOT = Path(__file__).resolve().parents[4]

# Measured in docs/orchestration/measurements.md: cheapest candidate with reliable tool calling.
DEFAULT_LLM_MODEL = "vertex-ai-gemini-3-flash-preview"
DEFAULT_DEMO_NOW = datetime(2026, 3, 9, 9, 0, tzinfo=UTC)

FailSource = Literal["news", "email", "docs", "all"]


def _default_data_dir() -> Path:
    return REPO_ROOT / "data"


def _default_recordings_dir() -> Path:
    return REPO_ROOT / "data" / "recordings"


@dataclass(frozen=True)
class Settings:
    llm_model: str
    llm_mode: Literal["live", "replay"] = "replay"
    record: bool = False  # RECORD=1 (live mode only): write data/recordings/
    data_source: Literal["snapshot", "graph"] = "snapshot"
    data_dir: Path = field(default_factory=_default_data_dir)  # MPA_DATA_DIR
    recordings_dir: Path = field(default_factory=_default_recordings_dir)  # MPA_RECORDINGS_DIR
    demo_now: datetime = DEFAULT_DEMO_NOW  # DEMO_NOW; the only "now" the agent may use
    fail_source: FailSource | None = None  # FAIL_SOURCE
    max_steps_per_agent: int = 8  # MAX_STEPS_PER_AGENT
    max_tokens: int = 80_000  # MAX_TOKENS (whole run)
    max_cost_usd: float = 0.05  # MAX_COST_USD (whole run)
    subagent_timeout_s: float = 45.0
    replay_delay_ms: int = 250  # REPLAY_DELAY_MS: simulated per-call latency in replay
    tracing: Literal["off", "langfuse"] = "off"  # TRACING

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Build settings from `env`; with `env=None` load `.env` (if any) and use `os.environ`."""
        if env is None:
            from dotenv import load_dotenv

            load_dotenv(REPO_ROOT / ".env", override=False)
            env = os.environ

        def text(name: str) -> str | None:
            value = env.get(name)
            return value.strip() if value is not None and value.strip() else None

        def choice(name: str, allowed: tuple[str, ...], default: str) -> str:
            value = (text(name) or default).lower()
            if value not in allowed:
                raise ValueError(f"{name} must be one of {', '.join(allowed)}; got {value!r}")
            return value

        def number(name: str, default: float, kind: type[int] | type[float]) -> float:
            raw = text(name)
            if raw is None:
                return default
            try:
                return kind(raw)
            except ValueError:
                raise ValueError(f"{name} must be a number; got {raw!r}") from None

        fail = text("FAIL_SOURCE")
        if fail is not None and fail.lower() not in ("news", "email", "docs", "all"):
            raise ValueError(f"FAIL_SOURCE must be one of news, email, docs, all; got {fail!r}")
        data_dir = Path(text("MPA_DATA_DIR") or _default_data_dir())
        recordings = Path(text("MPA_RECORDINGS_DIR") or _default_recordings_dir())
        return cls(
            llm_model=text("LLM_MODEL") or DEFAULT_LLM_MODEL,
            llm_mode=cast(
                Literal["live", "replay"], choice("LLM_MODE", ("live", "replay"), "replay")
            ),
            record=(text("RECORD") or "").lower() in ("1", "true", "yes", "on"),
            data_source=cast(
                Literal["snapshot", "graph"],
                choice("DATA_SOURCE", ("snapshot", "graph"), "snapshot"),
            ),
            data_dir=data_dir,
            recordings_dir=recordings,
            demo_now=_parse_now(text("DEMO_NOW")),
            fail_source=cast(FailSource, fail.lower()) if fail else None,
            max_steps_per_agent=int(number("MAX_STEPS_PER_AGENT", 8, int)),
            max_tokens=int(number("MAX_TOKENS", 80_000, int)),
            max_cost_usd=float(number("MAX_COST_USD", 0.05, float)),
            replay_delay_ms=int(number("REPLAY_DELAY_MS", 250, int)),
            tracing=cast(Literal["off", "langfuse"], choice("TRACING", ("off", "langfuse"), "off")),
        )


def _parse_now(raw: str | None) -> datetime:
    if raw is None:
        return DEFAULT_DEMO_NOW
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"DEMO_NOW must be an ISO-8601 timestamp; got {raw!r}") from None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

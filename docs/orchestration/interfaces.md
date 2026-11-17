# Cross-task Python interfaces (authoritative)

Gate-1 tasks (S1 core, S2 data, S3 API+tracing, S4 evals) are built in parallel in separate worktrees, so they cannot see each other's code. They integrate through the interfaces below. The contract task (G0b) writes them verbatim into `agent/src/mpa/contract/interfaces.py` (and `settings.py` for `Settings`), re-exported from `mpa.contract`. Service tasks import these and **must not change them**; if one is unusable, stop and report.

Types such as `Email`, `ChatMessage`, `Doc`, `CalendarEvent`, `Contact`, `NewsItem`, `SourceItem`, `SearchHit`, `BriefingRequest`, `BriefingPack`, `AgentEvent`, `EvalResult` are the generated Pydantic models in `mpa.contract.models` (mirrors of the zod/JSON Schema contract).

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Literal, Protocol
from pydantic import BaseModel

CitationType = Literal["email", "chat", "doc", "news", "contact", "cal"]

# ---------------------------------------------------------------- LLM
class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]            # JSON Schema object

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]

class LLMMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None   # assistant only
    tool_call_id: str | None = None            # tool only
    name: str | None = None                    # tool only

class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

class LLMResponse(BaseModel):
    message: LLMMessage
    usage: Usage
    model: str
    finish_reason: str | None = None
    latency_ms: int = 0

class LLMClient(Protocol):
    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tag: str | None = None,          # logical label, e.g. "news:step2"; NOT part of the replay key
    ) -> LLMResponse: ...

# ---------------------------------------------------------------- data
class DataSource(Protocol):
    # All methods async. Search methods return at most `limit` (<= 10) SearchHit, each <= 4 KB.
    async def search_email(self, query: str, *, limit: int = 10) -> list[SearchHit]: ...
    async def get_email(self, id: str) -> Email: ...                 # raises KeyError if unknown
    async def search_chat(self, query: str, *, limit: int = 10) -> list[SearchHit]: ...
    async def get_chat(self, id: str) -> ChatMessage: ...
    async def search_docs(self, query: str, *, limit: int = 10) -> list[SearchHit]: ...
    async def get_doc(self, id: str) -> Doc: ...
    async def get_calendar(
        self, *, start: datetime | None = None, end: datetime | None = None, query: str | None = None
    ) -> list[CalendarEvent]: ...                                    # time-window and/or text filter
    async def search_news(self, query: str, *, limit: int = 10) -> list[SearchHit]: ...
    async def get_news(self, id: str) -> NewsItem: ...
    async def get_contact(self, id: str) -> Contact: ...
    async def find_contacts(self, query: str, *, limit: int = 10) -> list[SearchHit]: ...
    async def get_source(self, type: CitationType, id: str) -> SourceItem: ...   # for GET /sources/{type}/{id}

class DataSourceError(Exception):
    """Raised for transient/unavailable source failures (retryable). KeyError means unknown id (not retryable)."""

# ---------------------------------------------------------------- tracing (sync, non-blocking, never raises)
class Span(Protocol):
    def set(self, **attrs: Any) -> None: ...
    def end(self, *, error: str | None = None) -> None: ...

class Tracer(Protocol):
    def start_run(self, run_id: str, *, name: str, input: dict[str, Any]) -> Span: ...
    def start_span(
        self, parent: Span, name: str, *, kind: Literal["agent", "step", "tool", "llm"], input: Any = None
    ) -> Span: ...
    def record_llm(
        self, parent: Span, *, model: str, input: Any, output: Any, usage: Usage, latency_ms: int
    ) -> None: ...
    def flush(self) -> None: ...

class NullSpan: ...            # implements Span as no-ops
class NoopTracer: ...          # implements Tracer, returns NullSpan; used when TRACING=off

# ---------------------------------------------------------------- settings
@dataclass(frozen=True)
class Settings:
    llm_model: str
    llm_mode: Literal["live", "replay"] = "replay"
    record: bool = False                       # RECORD=1 (live mode only): write data/recordings/
    data_source: Literal["snapshot", "graph"] = "snapshot"
    data_dir: Path = ...                        # MPA_DATA_DIR, default <repo>/data
    recordings_dir: Path = ...                  # MPA_RECORDINGS_DIR, default <repo>/data/recordings
    demo_now: datetime = ...                    # DEMO_NOW; the only "now" the agent may use
    fail_source: Literal["news", "email", "docs", "all"] | None = None   # FAIL_SOURCE
    max_steps_per_agent: int = 8                # MAX_STEPS_PER_AGENT
    max_tokens: int = 80_000                    # MAX_TOKENS (whole run)
    max_cost_usd: float = 0.05                  # MAX_COST_USD (whole run)
    subagent_timeout_s: float = 45.0
    replay_delay_ms: int = 250                  # REPLAY_DELAY_MS: simulated per-call latency in replay so the UI timeline is watchable
    tracing: Literal["off", "langfuse"] = "off" # TRACING
    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings": ...   # loads .env via python-dotenv if env is None

# ---------------------------------------------------------------- run wiring
@dataclass
class RunDeps:
    llm: LLMClient
    data: DataSource
    tracer: Tracer
    settings: Settings
```

## Entry points each task must provide (exact names and signatures)

| Owner | Module | Symbol |
|-------|--------|--------|
| S1 | `mpa.llm` | `build_llm_client(settings: Settings) -> LLMClient` (live → LiteLLM client; replay → ReplayClient; live+record → recording wrapper) |
| S1 | `mpa.agents.orchestrator` | `async def run_briefing(request: BriefingRequest, deps: RunDeps) -> AsyncIterator[AgentEvent]` — async generator; events are yielded as they happen (sub-agents run concurrently and push to one queue); the last event is always `run_done`; never raises for expected failures (sources down, budgets, bad model output): those become events + a partial briefing |
| S2 | `mpa.data` | `build_data_source(settings: Settings) -> DataSource` (`snapshot` → `FakeDataSource(settings.data_dir)`, `graph` → `GraphDataSource` stub whose methods raise `NotImplementedError`) |
| S2 | `mpa.data` | `FakeDataSource(data_dir: Path)` — reads `data/*.jsonl` as laid out in `data/README.md`; BM25 via `rank_bm25`; deterministic |
| S3 | `mpa.tracing` | `build_tracer(settings: Settings) -> Tracer` (`off` → `NoopTracer`; `langfuse` → `LangfuseTracer`, falls back to `NoopTracer` with one warning if keys/host are missing or Langfuse is unreachable) |
| S3 | `mpa.api.app` | `app: FastAPI` and `create_app(run_fn=None, deps=None) -> FastAPI`; default `run_fn` is `mpa.agents.orchestrator.run_briefing` imported lazily; `deps` defaults to wiring through the three `build_*` functions above |
| S4 | `mpa.evals` | `python -m mpa.evals [--client halden|brightmoor|kettle|all] [--scenario ...] [--live]` writes `evals/results/latest.md` and `latest.json` |

## Behavioural rules shared by everyone
- "Now" is `settings.demo_now`, never the wall clock, so prompts and results are deterministic.
- Replay keys are the SHA-256 of canonical JSON of `{model, messages, tools, temperature, max_tokens}` (sorted keys, no `tag`, no run ids, no timestamps, no URLs/headers/keys). Prompts must therefore be a pure function of the data and the request.
- Prompts that include email/doc/chat/news text must wrap it as untrusted data (delimited, with an instruction that it is data and never instructions).
- No tool anywhere sends, writes or deletes anything. The tool list is read-only by construction.
- Errors: `KeyError` = unknown id (not retried, reported to the model as a tool error); `DataSourceError`/timeouts = transient (retried once with backoff, then `subagent_failed` if the sub-agent cannot proceed).

## Event order and delivery of the finished briefing (D9, added after G0b)
`run_briefing` yields: `run_started`, `plan`, per sub-agent `subagent_started` → (`tool_call` → `tool_result` | `retry`)* → `subagent_done` | `subagent_failed` (agents interleave; `budget_hit` at most once, anywhere), then `verifier_result`, then **exactly 7 `draft` events, one section each in canonical order, only the last with `complete=true`**, then `run_done` (always last, even on failure). Only verified sentences are emitted. The finished `BriefingPack` is rebuilt by `assemble_pack(events)` / `assemblePack(events)` from `mpa.contract` / `@mpa/contract` (added by task g0c-assemble). The API streams these events as they are; there is no separate pack endpoint. `packages/contract/fixtures/runs/*.events.json` are complete example streams (and `*.pack.json` the expected assembled packs).

**Added by g0c:** the `plan` event MUST carry `meeting_title` and `meeting_start` (from the resolved `CalendarEvent.title` / `.start`); `assemblePack` raises without them. Agent→gap source mapping used by `assemble_pack`: correspondence=email, documents=docs, news=news, attendees=contacts. Read `packages/contract/EVENTS.md` for the full event rules and `packages/contract/fixtures/runs/*` for complete example streams.

# Task s3-api — Gate 1: FastAPI service, SSE streaming, /sources, /health, optional Langfuse tracing, docker-compose

Target wall time: about 45 minutes. No live LLM calls needed (use a fake `run_fn`).

## Goal
Expose the agent over HTTP on `http://localhost:8000` and add optional Langfuse tracing behind the `Tracer` interface. The orchestrator (S1), data layer (S2) and evals (S4) are being built in parallel; bind to the interfaces in `docs/orchestration/interfaces.md` / `agent/src/mpa/contract/interfaces.py` (already on `main`) and test with fakes.

## Owned files
- `agent/src/mpa/api/**`, `agent/src/mpa/tracing/**`
- `docker-compose.yml`
- `agent/tests/test_api*.py`, `agent/tests/test_tracing*.py`
- `docs/orchestration/reports/s3-api.md`

Must NOT touch: contract (`packages/contract/**`, `agent/src/mpa/contract/**`), `data/**`, `agent/src/mpa/{llm,loop,agents,guardrails,data,evals}/**`, `apps/**`, `evals/**`, `Makefile`, root config. `agent/pyproject.toml`: additive deps only (e.g. `langfuse` as an optional dependency group/extra, imported lazily so everything works without it).

## Deliverables
### API (`mpa/api/`)
- `create_app(run_fn=None, deps=None) -> FastAPI` and module-level `app = create_app()` (the existing `mpa.api.app:app` is a skeleton; replace its contents but keep `GET /health` working and the import path `mpa.api.app:app`, which `make dev` runs with uvicorn on port 8000).
  - Default `run_fn` = `mpa.agents.orchestrator.run_briefing`, imported lazily at first request so the app starts and `/health` works even before S1 is merged; default `deps` are built lazily from `Settings.from_env()` through `mpa.llm.build_llm_client`, `mpa.data.build_data_source`, `mpa.tracing.build_tracer` (all lazy-imported; if a builder is missing return a clear 503 JSON `{ "error": "service_unavailable" }` for that route only).
- `GET /health` → `{"status":"ok", "version", "llm_mode", "data_source", "tracing"}`; < 1 s; never touches the LLM or data; contains no secrets/URLs.
- `POST /briefings` body `BriefingRequest` (contract model; 422 on invalid). Response `text/event-stream`: each `AgentEvent` is one SSE message with `event: <type>` and `data: <compact JSON of the contract AgentEvent>` (one JSON per message; ≤ 8 KB each; validate through the contract model before sending; an event failing validation is replaced by an `run_done`-safe error path, never a half-written frame). Headers: `Cache-Control: no-cache`, `X-Accel-Buffering: no`. Flush the first byte immediately (send a `: stream-open` comment right away) so the first SSE event arrives < 3 s; keep-alive comment every 10 s. The stream ends after `run_done`. If the client disconnects, cancel the run and its tasks (test it). Unexpected exceptions inside `run_fn` become a final `run_done` with `partial=true` and a gap — build that event with the contract models; never leak tracebacks, URLs or env values.
- `GET /sources/{type}/{id}` → `SourceItem` JSON via `deps.data.get_source`; `type` ∈ email|chat|doc|news|contact|cal; 404 `{ "error": "not_found" }` for unknown id, 422 for bad type; id must match the contract's id pattern for that type.
- CORS: allow `http://localhost:3000` and `http://127.0.0.1:3000` only (GET, POST, OPTIONS).
- Request logging without bodies or env values.

### Tracing (`mpa/tracing/`)
- `build_tracer(settings) -> Tracer`: `off` → `NoopTracer` (from `mpa.contract`). `langfuse` → `LangfuseTracer` implementing the `Tracer`/`Span` protocols: one trace per run (`run_id`), nested spans for agents, steps and tool calls, generations for LLM calls with model, input/output, token usage and cost (`record_llm`). Reads `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` from env (names only in code and docs). The `langfuse` import is lazy; if the package, keys or host are missing, or Langfuse is unreachable, log ONE warning (without the host value) and fall back to `NoopTracer`. A tracer must never raise into the run and must never block it (buffer + flush in background / at `flush()`); truncate large inputs/outputs; never send env values, URLs or headers as trace content.
- `docker-compose.yml` (repo root): self-hosted Langfuse reachable on **http://localhost:3100** (map host 3100 → container 3000), with its database and any services that version needs, named volumes, healthchecks, and a pre-seeded local project/keys via the headless-init env vars if the chosen image version supports them (use clearly-labelled local-dev-only placeholder secrets that are NOT real credentials; document how to create keys in the UI otherwise). Prefer the simplest Langfuse version that needs the fewest containers. Add a comment header explaining it is optional. You likely cannot run docker here; if you can, verify it comes up; otherwise validate syntax with `docker compose config` if available and say clearly in the report that it was not started.

## Tests (offline, in `pnpm check`)
`httpx.ASGITransport`/`TestClient`: `/health` shape and speed; SSE framing (event name, JSON data, order preserved, ends after `run_done`, first frame immediately even if the fake run is slow); stream payloads validate against the JSON Schema; 422 on bad body; client disconnect cancels a long fake run; `run_fn` exception → terminal `run_done` partial; `/sources` for all six types using a fake `DataSource` (plus 404/422); CORS headers; `build_tracer` fallbacks (missing keys, import error, unreachable host → Noop, one warning, no secret in log output); `LangfuseTracer` against a fake langfuse client object (span nesting, usage/cost recorded, never raises). 

## Acceptance
- `pnpm check` green, offline, no API key.
- `make dev-api` starts; `curl localhost:8000/health` < 1 s.
- Merge report committed (note how you verified SSE first-event latency and whether docker compose was actually started).

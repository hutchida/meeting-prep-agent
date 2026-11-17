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

---

# Common rules (apply to every task)

## Project in one paragraph
`meeting-prep-agent` is a public portfolio repo: a hand-built multi-agent system (hand-written agent loop, parallel sub-agents, guardrails, tracing, evals, failure handling) that prepares cited meeting briefing packs from fake email/chat/docs/calendar/contacts/news. Monorepo: `packages/contract` (zod + JSON Schema + fixtures, single source of truth), `packages/capture` (shared Playwright capture), `apps/web` (Next.js + Tailwind, :3000), `agent/` (Python 3.12 + uv + FastAPI, :8000, outside the pnpm workspace), `data/` (committed fake dataset), `evals/`, `docs/`. Read `DECISIONS.md` first; it records choices already made (notably: the LiteLLM proxy has NO Claude Haiku alias, so the model comes from `LLM_MODEL`).

## Setup
Your worktree is a fresh checkout of `main`. The master has copied a gitignored `.env` into it (names only here: `LITELLM_BASE_URL`, `LITELLM_API_KEY`, `LLM_MODEL`, `LLM_MODE`, `DATA_SOURCE`, `DEMO_NOW`, `TRACING`). Run `pnpm install` then `cd agent && uv sync`. Python code loads `.env` via python-dotenv; do not source it into your shell output.

## Secrets rule (hard)
- Never print, log, echo, commit, or paste a secret value. This includes `LITELLM_API_KEY`, `LITELLM_BASE_URL` (treat the URL as secret), and `LANGFUSE_*`.
- Never `cat .env`, never run `env`/`printenv` unfiltered, never put request headers, URLs or keys into `data/recordings/`, traces, logs, reports, test snapshots, fixtures or error messages. Redact before writing.
- `.env.example` has names only. `.env` is gitignored. Before every commit run `git diff --cached | grep -i -E "sk-|proxy-host|Bearer " ` and confirm it prints nothing.
- No `ANTHROPIC_API_KEY` is used. All LLM calls go through the `LLMClient` interface to the LiteLLM proxy (OpenAI-compatible `/chat/completions` with tool calling).

## Ownership and boundaries
- Edit ONLY the files your task owns (listed in the task). Do not touch anything else, including other tasks' files, root config, `Makefile`, CI, lockfiles' structure.
- Exceptions: you may add dependencies to your own package's manifest (`agent/pyproject.toml` dependencies, `packages/<x>/package.json`) and commit the resulting `uv.lock` / `pnpm-lock.yaml` change; the master resolves lockfile conflicts at merge by regenerating.
- **Contract changes are forbidden** unless you are the contract task (G0b). The contract is `packages/contract/**` (zod schemas, `schema/*.json`, `fixtures/*`) and the Pydantic mirror in `agent/src/mpa/contract/**`. If the contract is missing something you need, DO NOT edit it and DO NOT add fields: stop, record the gap in your report, and ask the master (see Orchestration below). Services bind to the merged contract and fixtures exactly; no new fields.
- Do not add a remote, push, open a PR, or touch other worktrees or `main`. Commit to your own branch only, often, with clear messages.

## Engineering rules
- No agent frameworks (no LangChain, LangGraph, CrewAI, OpenAI/Anthropic Agents SDKs). Call the model only through `LLMClient`.
- Python: 3.12, `ruff` (line length 100), `mypy --strict`, `pytest` with a mocked `LLMClient`. Fully offline unit tests; no API key.
- TypeScript: strict, eslint clean, vitest.
- `pnpm check` (lint + typecheck + vitest + contract tests + `uv run pytest`) must pass offline with no API key and in well under 3 minutes.
- Keep comments sparse; only for non-obvious behaviour.

## Acceptance
Done = `pnpm check` green on your branch + the task-specific commands and time budgets in the task + merge report committed + `worker_done` sent.

## Merge report (required)
Before finishing, write `docs/orchestration/reports/<task-id>.md` and commit it. Use exactly:

```
# Merge report: <task-id>
- Model(s): <as reported by your harness, or "unavailable">
- Wall time start→ready: <start UTC> → <end UTC> (<minutes>); active time: <minutes or "unavailable">
- Tokens in/out: <numbers or "unavailable">
- Cost: <USD or "unavailable">
- Bottlenecks: <waits, retries, flaky checks, unclear instructions, contract gaps>
- Checks run + results: <command → result, one per line>
- What was built: <short list>
- Known gaps / follow-ups: <short list>
```
Record `date -u` at the very start and at the end. Never estimate a metric you cannot read; write "unavailable". (The master fills token/cost from the harness session export if you cannot.)

## Orchestration (you are a supervised worker)
Your launch prompt carries a live preamble with the exact `orca` command, handle, Task ID and Dispatch ID if you were started through orchestration: follow it exactly. In short: heartbeat at the cadence given, use the preamble's `ask` command for blocking questions (never an interactive question tool), check for coordinator follow-ups at natural checkpoints and before finishing, and send `worker_done` exactly once with a three-sentence summary and `--outcome succeeded` or `--outcome failed`. If you were started without a preamble, just finish and say so in your final message.

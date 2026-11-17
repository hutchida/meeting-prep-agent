# Task g0c-assemble — Gate 0c: close the "how does the finished briefing reach clients" gap

Small follow-up to the contract task (g0b, already merged on `main`). You own the contract again for this task only. Target wall time: about 20 minutes. No LLM calls.

## Problem
The 8 KB `AgentEvent` cap means a whole `BriefingPack` (up to 40 KB) cannot travel in one event, and nothing in the contract delivers the final verified pack to the web UI, the API consumers or the eval harness. DECISIONS.md D9 records the decision below.

## Decision to implement (D9)
Fixed event order for a run:
`run_started`, `plan`, then per sub-agent `subagent_started` → (`tool_call` → `tool_result` | `retry`)* → `subagent_done` | `subagent_failed` (the four agents interleave arbitrarily; `budget_hit` may appear once anywhere), then `verifier_result`, then **exactly 7 `draft` events, one section each in canonical order** (`meeting_at_a_glance` … `talking_points_and_risks`; only the **last** has `complete=true`), then `run_done`. Only verified sentences are ever emitted in `draft` events (the Verifier runs before them; unverified Writer text never leaves the orchestrator).

## Deliverables (you may change what is needed inside the owned files)
1. `assemble_pack(events) -> BriefingPack` in **both** languages with identical behaviour and shared test cases:
   - TypeScript: `packages/contract/src/assemble.ts` exported from `src/index.ts` (`assemblePack(events: AgentEvent[]): BriefingPack`).
   - Python: `agent/src/mpa/contract/assemble.py` exported from `mpa.contract` (`assemble_pack(events: Sequence[AgentEvent]) -> BriefingPack`).
   Inputs may arrive in any interleaving of the allowed orders and with events sorted by `seq`; assemble sorts by `seq`, tolerates missing optional events (e.g. no `verifier_result` → counts derived from sentences; no `run_done` → partial=true with a gap), derives: `run_id`, `model` (run_started), `client`/`meeting` (plan), sections (the 7 drafts, by section id), `gaps` (from `subagent_failed` (reason/error), `budget_hit`, and `gaps` carried by `subagent_done`; de-duplicated, stable order), `partial` (any gap, a budget hit, or run_done.partial), `verifier` (verifier_result), `stats` and duration (run_done). Raise a clear error (`PackAssemblyError`) if sections are missing and the run is marked complete. The result must validate against the `BriefingPack` schema and the 40 KB limit.
   - If the existing events lack information needed to build a valid `BriefingPack` (for example the meeting title/start), **extend the events minimally and additively** (e.g. optional-but-always-sent fields on `PlanEvent`) and update schema export, generated Pydantic models, all fixtures and tests. Prefer deriving over adding. Record exactly what you changed in your report (the master will tell downstream tasks).
2. **Run fixtures** in `packages/contract/fixtures/runs/`: complete ordered event streams as JSON arrays: `run.brightmoor.normal.events.json` (all four agents with tool calls, interleaved, ≥ 25 events), `run.brightmoor.news_down.events.json` (news: `retry` then `subagent_failed`, "could not be reached" note in `recent_news`, `partial=true`), `run.halden.budget_hit.events.json` (a `budget_hit`, partial with gaps), plus the expected assembled packs `*.pack.json` next to each. Content must be realistic and consistent with the committed dataset in `data/` (real ids, real people, proper citations for Brightmoor Renewables' Thursday 2026-03-12 meeting; read `data/PLOT.md`). Every event ≤ 8 KB, every pack ≤ 40 KB. Tests (vitest + ajv, pytest + jsonschema + Pydantic): every event validates, `seq` is strictly increasing, the order rules above hold (write a small `check_event_order` helper in both languages: sections canonical, only last draft complete, `run_done` last, `verifier_result` before the drafts), `assemble` of each stream equals the `*.pack.json`, TS and Python outputs are equal for the same inputs.
3. Documentation: update the event-order description in `docs/orchestration/interfaces.md`? No: you must not edit it. Instead add `packages/contract/EVENTS.md` describing the event order, per-event meaning, which events a UI should render, and how to call `assemblePack`/`assemble_pack`. Keep it under one page.
4. Everything idempotent (`schema:export`, `gen_models.py`) and `pnpm check` green offline.

## Owned files
`packages/contract/**`, `agent/src/mpa/contract/**`, `agent/scripts/gen_models.py`, `agent/tests/test_contract*.py`, `docs/orchestration/reports/g0c-assemble.md`. Must NOT touch: `data/**` (read only), `apps/**`, `agent/src/mpa/{llm,loop,agents,guardrails,data,api,tracing,evals}/**`, `evals/**`, `docs/**` other than your report, `DECISIONS.md`, `Makefile`, root config. (Interfaces in `interfaces.py` / `settings.py` must not change.)

## Acceptance
`pnpm check` green offline; schema export and model generation idempotent; TS/Python assembly parity tests pass; merge report committed (list every contract change precisely).

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

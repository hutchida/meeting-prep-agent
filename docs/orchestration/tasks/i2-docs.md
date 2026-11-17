# Task i2-docs — Gate 2: README, architecture docs, DECISIONS polish

Target wall time: about 40 minutes. No demo replays and no screenshot tooling in this task (the master adds screenshots/GIF during Rehearsal and links them; leave clearly marked placeholders: `<!-- MEDIA:demo-gif -->`, `<!-- MEDIA:screenshots -->`). No live LLM calls.

## Goal
A README and docs that make a hiring manager understand in 2 minutes what this is, why it's good engineering, and how to run it, with real numbers.

## Owned files
- `README.md`
- `docs/**` except `docs/orchestration/**` and `docs/media/**` (e.g. `docs/architecture.md`, `docs/guardrails.md`, `docs/evals.md`)
- `DECISIONS.md` (keep every existing entry verbatim; you may add entries and tidy formatting; do not delete or rewrite history)
- `docs/orchestration/reports/i2-docs.md`

Must NOT touch: code (`agent/**`, `apps/**`, `packages/**`), `data/**`, `evals/**` (read only), `Makefile`, CI, `docs/demo.md` (the master writes it in Rehearsal), `docs/orchestration/**` other than your report.

## Inputs (read them; everything you write must match the merged code)
The merged code on `main`: `agent/src/mpa/**` (llm, loop, agents, guardrails, data, api, tracing, evals), `packages/contract` (schemas), `apps/web`, `evals/results/latest.md` + `latest.json` (real eval numbers), `evals/gold`, `data/README.md`, `Makefile`, `docker-compose.yml`, `.env.example`, `docs/orchestration/measurements.md` (model, latency, price, Enron measurements), `DECISIONS.md`, `docs/orchestration/reports/*.md` (what each part measured).

## README.md must contain, in order
1. Title, one-line pitch, and the badges you can honestly claim offline (licence MIT; CI badge only as a comment/TODO since nothing is pushed). Placeholder for the demo GIF.
2. **What it is** (3–5 sentences): hand-built multi-agent system for long-horizon tasks: hand-written agent loop (no frameworks), parallel sub-agents, guardrails, tracing, evals, failure handling; data behind an interface so Microsoft Graph can replace the fake snapshot later.
3. **Architecture**: a Mermaid diagram (orchestrator → plan → 4 parallel sub-agents → Writer → Verifier; LLMClient (LiteLLM proxy / replay) and DataSource (fake snapshot / Graph stub) interfaces; API SSE → web UI; tracing to Langfuse) and a short walkthrough of one run (which events are emitted when).
4. **Quick start**: prerequisites (Node via `.nvmrc`, pnpm from `packageManager`, uv, Python 3.12), `make setup`, `make dev` (URLs: UI :3000, API :8000/health, Langfuse :3100 optional), `make test` (= `pnpm check`, offline, no API key), `make eval`, `make data`; `.env` setup using names from `.env.example` only (no values, never show the proxy URL), `LLM_MODE=replay` (offline demo path) vs `live`, `RECORD=1`, `FAIL_SOURCE`, `DATA_SOURCE`, `TRACING=langfuse` + `docker compose up`.
5. **How the agent loop works**: tool-use loop, parallel sub-agents with `asyncio`, structured outputs validated with Pydantic (retry once, degrade), Writer, Verifier. Short code-pointer list with file paths.
6. **Guardrails**: cite-or-drop verifier, read-only tool set (no send/write/delete), untrusted-data handling and prompt-injection test, budgets (steps/tokens/cost) with partial briefings, retries and fault injection (`FAIL_SOURCE`), size limits from the contract.
7. **Evals**: how they work (gold briefings, fact lists, traps, LLM judge prompt location), the **results table copied from `evals/results/latest.md`** (real numbers; if a number is missing say so, never invent), failure-test table.
8. **Cost and latency per briefing**: from the eval results and `measurements.md`, with the model used and the fact that the proxy has no Haiku alias (see `DECISIONS.md`) — be straightforward about it.
9. **Demo**: placeholders for GIF and screenshots; 5-step demo path summary linking to `docs/demo.md` (it will exist after Rehearsal).
10. **Project layout** tree (monorepo) and the contract-first approach (zod → JSON Schema → Pydantic, size limits).
11. **Known limitations** (honest: fake data, small model, heuristic verifier support check, English only, single-user, no auth, etc. — derive from the merged code and the task reports' "known gaps").
12. **Next steps**: Microsoft Graph data source, self-hosted model via vLLM behind the same `LLMClient`, MCP server exposing the briefing tool, richer evals, streaming Writer.
13. Licence and dataset attribution (Enron sample via CMU, from `data/README.md`).

Also write `docs/architecture.md` (component responsibilities, data flow, event sequence, interfaces), `docs/guardrails.md` (each guardrail, where it lives, how it is tested), and `docs/evals.md` (method, scenarios, how to add a client) — concise.

## Rules
- Every claim must be checkable in the repo: verify commands you document by running the offline ones (`make test`, `pnpm check`, `cd agent && uv run pytest`) and the docs' links/paths exist. Do not run live LLM commands.
- Never print or document secret values or the proxy URL; env var NAMES only.
- Tone: plain, specific, honest. No marketing filler, no emoji. Don't overclaim (e.g. don't say "production-ready").

## Acceptance
- `pnpm check` green (docs must not break lint), all relative links resolve (script a quick check), Mermaid renders (valid syntax), numbers match `evals/results/latest.md`.
- Merge report committed.

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

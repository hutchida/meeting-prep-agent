# Task s4b-eval-live — Gate 1: live eval runs (follow-up to s4-evals)

You are continuing task `s4-evals` (read `docs/orchestration/tasks/s4-evals.md`, section "Live runs", and `docs/orchestration/reports/s4-evals.md`). The orchestrator (S1), data (S2), API (S3) and capture (C1) are now merged on `main`. Target wall time: 25 minutes. Live LLM spend cap for this task: US$1.50 total (the proxy bills per call; `x-litellm-response-cost` is captured by the client).

## Do
1. In your worktree (branch `s4-evals`) run `git merge main`; run `pnpm install` and `cd agent && uv sync`; `pnpm check` must be green.
2. Wire the harness to the real orchestrator (`mpa.agents.orchestrator.run_briefing`, `mpa.llm.build_llm_client`, `mpa.data.build_data_source`, `mpa.tracing.build_tracer`), fix any integration mismatch that is inside your owned files (`evals/**`, `agent/src/mpa/evals/**`, `agent/tests/test_evals*.py`). Event rules: read `packages/contract/EVENTS.md` and use `assemble_pack`; the pack is rebuilt from events (there is no pack endpoint).
3. Run `make eval` (3 clients, normal scenario, live) and check it finishes in < 5 minutes. Then run each failure scenario once: `cd agent && uv run python -m mpa.evals --scenario news_down|empty_client|injection|budget_hit` (use the client each scenario defines; `injection` on Halden Pay).
4. Calibrate the judge: read a sample of the judge's verdicts against the actual briefing text and gold facts; fix judge-prompt or parsing bugs (inside `evals/prompts/**`, `mpa/evals/**`). Do NOT soften scoring to look good: report honest numbers. If the judge disagrees with your own reading, say so in the report.
5. Commit `evals/results/latest.md` and `evals/results/latest.json` from a real run (no URLs/keys/headers inside; check). The table must contain per-client fact recall, hallucinations, citation accuracy, steps, tokens, cost, latency, injection result, plus the failure-scenario pass/fail table.
6. Do NOT edit S1/S2/S3 code. If an eval fails because of an orchestrator problem, record the symptom precisely (client, scenario, event excerpt, expected vs actual, run count) in your report under "Orchestrator findings" so the master can route it.
7. Update `docs/orchestration/reports/s4-evals.md` (append a "Live runs" section: commands, wall time, per-client numbers, cost of the eval run, failures). Commit, then `worker_done`.

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

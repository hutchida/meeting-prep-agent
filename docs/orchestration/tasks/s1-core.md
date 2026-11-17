# Task s1-core — Gate 1: LLM client, agent loop, orchestrator, sub-agents, Writer, Verifier, budgets, faults

This is the heart of the project (what a hiring manager will read). Quality, determinism and testability matter. Target wall time: 75–90 minutes. Live LLM spend for your own trials: under US$1.00 total, and only after the dataset layer (S2) has landed on `main` (see "Live trials").

## Goal
A hand-written agent loop with tool use, four parallel sub-agents, a Writer, a cite-or-drop Verifier, per-run budgets, retries, fault injection, record/replay of LLM calls. No agent frameworks. The model is called only through `LLMClient` (see `docs/orchestration/interfaces.md` and `agent/src/mpa/contract/interfaces.py`, merged on `main`; do not modify them).

## Owned files
- `agent/src/mpa/llm/**`, `agent/src/mpa/loop/**`, `agent/src/mpa/agents/**`, `agent/src/mpa/guardrails/**`
- `agent/tests/test_llm*.py`, `agent/tests/test_loop*.py`, `agent/tests/test_agents*.py`, `agent/tests/test_guardrails*.py`, `agent/tests/test_orchestrator*.py`
- `docs/orchestration/reports/s1-core.md`

Must NOT touch: contract (`packages/contract/**`, `agent/src/mpa/contract/**`), `data/**`, `agent/src/mpa/{data,api,tracing,evals}/**`, `apps/**`, `evals/**`, `docker-compose.yml`, `Makefile`, root config. `agent/pyproject.toml`: additive deps only. Other tasks are being built in parallel against the same interfaces (S2 data, S3 API/tracing, S4 evals, C1 capture); do not wait for them. In tests use your own in-memory fake `DataSource` and a scripted mock `LLMClient`.

## Inputs (already on main)
Contract fixtures in `packages/contract/fixtures/`; Pydantic models in `agent/src/mpa/contract/models.py`; `Settings`, `RunDeps`, `LLMClient`, `DataSource`, `DataSourceError`, `Tracer`, `NoopTracer`; dataset in `data/` with `data/README.md` and `data/PLOT.md` (what a good briefing for each client must contain, and the traps); `docs/orchestration/measurements.md` (recommended model, latency, price).

## Deliverables
### 1. `mpa/llm/`
- `LiteLLMClient(settings)`: `httpx.AsyncClient` POST `{LITELLM_BASE_URL}/chat/completions` (OpenAI-compatible, Bearer `LITELLM_API_KEY`, both read from env at construction; fail fast with a clear message that names only the variable NAMES if missing). Tool calling via `tools` + `tool_choice="auto"`. Map response → `LLMResponse` (tool calls parsed from JSON, `usage`, latency). Cost: `x-litellm-response-cost` header if present, else a small price table in `llm/pricing.py` keyed by model alias (use values/sources from `measurements.md`; unknown model → 0.0 plus a one-time warning). Transport errors: retry on 429/5xx/timeouts up to 2 times with backoff; raise `LLMError` whose message never contains the URL, headers or key (strip them from httpx exceptions). Per-call timeout 30 s.
- `ReplayClient(recordings_dir, delay_ms)`: key = SHA-256 of canonical JSON of `{model, messages, tools, temperature, max_tokens}` (sorted keys, compact separators, UTF-8; excludes `tag`). Hit → stored `LLMResponse` (after `delay_ms` sleep to make the UI timeline watchable). Miss → `ReplayMiss` carrying the hash and `tag`, never prompts' secrets.
- `RecordingClient(inner, recordings_dir)`: wraps a live client; writes `data/recordings/<hash>.json` = `{request: {model, messages, tools, temperature, max_tokens}, response: LLMResponse}` only (assert no URL/header/key text is present: add a redaction check that raises if `LITELLM_BASE_URL`/`LITELLM_API_KEY` values or `sk-` strings appear). Atomic write, stable formatting (sorted keys, indent=1, trailing newline) so diffs are reviewable.
- `build_llm_client(settings)`: live → `LiteLLMClient`; live+record → `RecordingClient(LiteLLMClient)`; replay → `ReplayClient`.
- Model-name hygiene: the request `model` is `settings.llm_model`.

### 2. `mpa/loop/` (the hand-written agent loop)
- `run_agent_loop(...)`: given a system prompt, user task, a tool registry (`ToolSpec` + async handler), a step budget, a shared `Budget`, an `emit(AgentEvent)` callback, a `Tracer` span and the output model, it: calls the LLM with tools; executes requested tool calls (parallel when several in one turn), appends tool results as `tool` messages; repeats until the model calls the mandatory terminal tool `submit_findings` (arguments validated against the `SubAgentOutput`-compatible model) or the step budget is hit. Tool results are truncated to ≤ 10 items and ≤ 4 KB per item before going to the model (contract limit), and wrapped as untrusted data (see Guardrails).
- Tool-call resilience: each tool call retries once with backoff (e.g. 0.25 s, jittered deterministically) on `DataSourceError`/timeout, emitting a `retry` event; `KeyError` → tool-error message to the model (no retry). After the retry fails: tool result is an error message to the model; if the sub-agent has no way forward it ends with `subagent_failed`.
- Pydantic-validated output: if `submit_findings` args fail validation, feed the validation error back once ("retry once with the error"), then degrade to an empty `SubAgentOutput` with a gap entry (never crash).
- Events emitted exactly as the contract's `AgentEvent` union (`tool_call`, `tool_result` summaries, `retry`, `subagent_started/done/failed`, …). Each event ≤ 8 KB: summarise, never embed full bodies.
- `Budget`: tracks steps per agent, tokens (in+out) and cost for the whole run; thread/async-safe; checked before every LLM call. On hit → `budget_hit` event once, all agents stop cleanly after their current call, Writer runs in degraded mode.

### 3. `mpa/agents/`
- `orchestrator.run_briefing(request, deps)` (exact signature in the spec): parse request → resolve client + meeting from the calendar relative to `settings.demo_now` (deterministic rules first: client name / alias match and day-of-week → calendar window; if ambiguous or not found, produce a clear partial briefing explaining what could not be resolved, still ending in `run_done`) → `plan` event → run the four sub-agents concurrently with `asyncio` (TaskGroup or gather, each with `subagent_timeout_s`; a failed/timed-out/cancelled one must not stop the others) → collect → Writer → Verifier → `draft`, `verifier_result`, `run_done` (with final stats and `partial`). Events are yielded as they happen via an `asyncio.Queue`; if the consumer stops iterating, cancel everything cleanly (no orphan tasks).
- Four sub-agents, each its own loop, prompt and read-only tool set built on the `DataSource`: **Correspondence** (email + chat: where things were left, open items), **Documents** (proposals, notes, contracts: context and commitments), **News** (recent coverage; ignores same-name companies), **Attendees** (contacts + past interactions). Tools: `search_*`, `get_*`, `get_calendar`, `find_contacts`, plus `submit_findings`. NO send/write/delete tool exists anywhere; add a test asserting the full tool registry only contains read-only names from an allow-list.
- **Writer**: one LLM call (no tools) that turns the validated findings into the 7 sections in fixed order (`meeting_at_a_glance`, `client_snapshot`, `recent_news`, `where_we_left_off`, `open_items`, `attendees`, `talking_points_and_risks`), strict JSON validated against the contract's `BriefingPack` section model (retry once with the error, then fall back to the **deterministic fallback writer** that renders findings into sections without an LLM). The fallback is also used when the budget is exhausted. Every factual sentence carries citations drawn only from the ids present in findings. Empty section → plain note ("No recent news found"), never invented content. A failed sub-agent → the matching section says so plainly ("News could not be reached.") and the pack has `partial=true` + `gaps`.
- **Verifier (cite-or-drop)** in `mpa/guardrails/verifier.py`: for every sentence, each cited id must exist (via `DataSource.get_source`) AND the cited source must support the sentence. Implement support as a deterministic check you can unit-test (e.g. overlap of content words, numbers, dates and proper nouns between the sentence and the cited item's text, with a documented threshold) and optionally one batched LLM check for borderline sentences only if budget allows. Unsupported sentences are removed and counted (`sentences_total/kept/dropped`, plus which ones, in `verifier_result`). Sections left empty by dropping say so plainly. Note-kind sentences are exempt.

### 4. `mpa/guardrails/` (the rest)
- **Prompt-injection handling:** all email/chat/doc/news text goes to the model inside clearly delimited untrusted-data blocks with an instruction that it is data and never instructions; a screening step flags instruction-like content in retrieved items (phrases like "ignore (all|your) (previous )?instructions", "forward all", "system:", requests to send/transfer/exfiltrate) and replaces the matching span in what the model sees with `[flagged: instruction-like text removed]` while recording the flag. Flags surface as a risk note in the final pack (id of the suspicious source, "contains instructions that were ignored"), never as an obeyed instruction and never as a fact about the client. Test with the injection email described in `data/PLOT.md` (Halden Pay) and with a mock model that "obeys" it: no tool exists that could act, and the Verifier drops any sentence echoing the attack.
- **Fault injection:** `FaultInjectingDataSource(inner, fail_source)` in `mpa/guardrails/faults.py`: `news` → all `search_news/get_news` raise `DataSourceError`; `email` → email and chat; `docs` → docs; `all` → everything. Source = `request.fail_source` or `settings.fail_source`. The run must still finish with a partial briefing: timeline shows `retry` then `subagent_failed` for the affected agent; Recent news says it could not be reached; every other section still renders.
- **Budgets** (see loop): `MAX_STEPS_PER_AGENT`, `MAX_TOKENS`, `MAX_COST_USD` from `Settings`. On hit: stop cleanly, partial briefing naming what's missing (a `gaps` entry with `reason: "budget"` per unfinished agent).

### 5. Determinism and performance
- Prompts are a pure function of the request, the data and `settings.demo_now`: no wall-clock times, uuids, random ordering (sort everything), or env values in any prompt (this is what makes replay keys stable). Run ids and `ts` live only in events.
- Targets: full run in replay mode < 10 s with the default `replay_delay_ms` (mind how many sequential calls each agent makes: keep sub-agents to ≲ 5 LLM calls, use parallel tool calls, keep prompts short); live run per client < 60 s and < US$0.05 with the recommended model; keep tool results compact to protect cost.

## Tests (offline, no API key, mocked LLMClient; all in `pnpm check`)
Loop (tool round trip, parallel tool calls, step budget, validation retry then degrade, tool retry event ordering), LiteLLM client against `httpx.MockTransport` (parsing, retries, error redaction: assert the message never contains URL/key), replay key stability + record→replay round trip + miss behaviour + redaction check, orchestrator end to end with scripted mock model and fake DataSource (events order: `run_started`, `plan`, 4× `subagent_started`, … `draft`, `verifier_result`, `run_done`; concurrency actually overlaps), Verifier (nonexistent id dropped, unsupported sentence dropped, supported kept, counts right, empty section note), fault injection for each of news|email|docs|all, budget hit (tokens and cost and steps) producing a partial pack with named gaps, sub-agent timeout, consumer disconnect cancels tasks, injection test, read-only tool allow-list, every emitted event ≤ 8 KB and the pack ≤ 40 KB and validating against the JSON Schema.

## Live trials (after S2 lands on main)
The master will message you when `mpa.data.build_data_source` is on `main`. Then: `git merge main` into your branch, and run each client once live (`LLM_MODE=live RECORD=` unset; `.env` is already in the worktree). Check: full run < 60 s, < US$0.05, 7 sections, citations valid, plausible content vs `data/PLOT.md`, injection not obeyed or repeated. Fix prompts, not the contract. Do NOT commit recordings (the master records the official demo set at the Gate-1 check); do not print URLs/keys. Total live spend ≤ US$1.00. If something in the contract or data prevents the targets, stop and report instead of working around it.

## Acceptance
- `pnpm check` green offline; unit tests cover the items above; merge report with measured live numbers (latency, tokens, cost per client) and anything that stops targets being met.
- `from mpa.llm import build_llm_client` and `from mpa.agents.orchestrator import run_briefing` work with the exact signatures in the interfaces spec.

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

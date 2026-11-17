# Task i1-web — Gate 2: Chat UI (Next.js App Router + Tailwind)

Target wall time: about 60 minutes. No demo replays and no screenshot tooling in this task: do not record demo runs, do not write Playwright scripts, do not touch `packages/capture` (another task owns it; you only implement the test ids it expects). Do not call the live LLM.

## Goal
A chat UI like Copilot in Teams on `http://localhost:3000` that talks to the API on `http://localhost:8000`: message box, three starter prompts, a live step timeline fed by SSE (plan, four parallel sub-agents, tool calls, retries, failures), the briefing rendered as markdown with clickable citations opening a source side panel, a "Simulate news outage" toggle, and run stats (steps, tokens, cost, time).

## Owned files
- `apps/web/**`
- `docs/orchestration/reports/i1-web.md`

Must NOT touch: `packages/**` (contract is read-only: import types/schemas from `@mpa/contract`; **no new fields, no new event types, no contract changes**, if something is missing, stop and report), `agent/**`, `data/**`, `docs/**` except your report, `README.md`, `DECISIONS.md`, `Makefile`, root config. Dependencies: add to `apps/web/package.json` only (keep them few: a markdown renderer such as `react-markdown` is fine; no UI kit required).

## Inputs (already on main)
- API (merged): `POST http://localhost:8000/briefings` (body `BriefingRequest` = `{message, fail_source?}`) streams SSE; each message is `event: <AgentEvent.type>` + `data: <AgentEvent JSON>`; stream ends after `run_done`. `GET /sources/{type}/{id}` returns a `SourceItem`. `GET /health`. CORS allows `http://localhost:3000`.
- Contract types and zod schemas in `@mpa/contract` (`AgentEvent`, `BriefingPack`, `BriefingRequest`, `SourceItem`, citation helpers `parseCitations`/`citationToken`); fixtures in `packages/contract/fixtures/` (valid AgentEvent and BriefingPack examples for every variant: use them for unit tests and Storybook-less development).
- `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`) is the only config; no secrets in the browser.

## UX requirements
1. **Landing/chat screen:** header ("Meeting Prep Agent"), empty state with **three starter prompt buttons**, exactly: "Prep me for my meeting with Halden Pay on Wednesday", "Prep me for my meeting with Brightmoor on Thursday", "Prep me for my meeting with Kettle & Crumb on Friday". Message box + send button; Enter to send; disabled while a run is active (with a visible stop button that aborts the fetch).
2. **Teams-Copilot feel:** user bubble right, assistant card left, calm neutral palette, readable type, good spacing, responsive down to ~900 px wide, keyboard accessible, visible focus rings, `aria-live` for streaming updates. Tasteful, not flashy; no emoji spam.
3. **Live step timeline** (inside the assistant card, above the briefing; collapsible once done): rows appear as SSE events arrive: plan (show the plan text), four sub-agents shown as parallel lanes/columns or a grouped list with per-agent status (running / retrying / failed / done) and their tool calls streaming under each (tool name + short args + result summary: item count and ids), retries (attempt, backoff, error summary) in amber, failures (`subagent_failed`) in red with the reason, budget hit notice, verifier result ("kept X of Y sentences, dropped Z"). Timeline row elements carry `data-testid="timeline-event"` with `data-type` (the AgentEvent type) and `data-agent` when the event has an agent. The container is `data-testid="step-timeline"`.
4. **Briefing:** when the `draft` event arrives show a skeleton/preview; when the final pack is available (`draft` after verification or the pack in `run_done`, whichever the contract defines; follow the contract exactly) render the 7 sections in order with titles. Container `data-testid="briefing"`; each section `data-testid="section-<id>"` with ids `meeting_at_a_glance, client_snapshot, recent_news, where_we_left_off, open_items, attendees, talking_points_and_risks`. Sentences render as markdown text; **citations** (structured `citations[]` and/or inline tokens like `[email:E123]`) render as small chips/superscripts, `data-testid="citation"` with `data-cite="email:E123"`. Empty sections show their note plainly. Partial packs show a clear "Partial briefing" banner listing `gaps` (source + reason).
5. **Source side panel:** clicking a citation opens a right-side panel (`data-testid="source-panel"`, close button `source-panel-close`, Esc closes) that fetches `GET /sources/{type}/{id}` and renders the item by type (email: from/to/date/subject/body; chat; doc with title/kind/body; news with source/date/url as plain text; contact; calendar event). Loading and error states. Treat all text as untrusted: render as text/markdown with no raw HTML, never `dangerouslySetInnerHTML`; links from data are not auto-opened.
6. **"Simulate news outage" toggle:** `data-testid="toggle-news-outage"`, sends `fail_source: "news"` in the request body. Place it near the message box with a short helper text.
7. **Run stats:** `data-testid="run-stats"` showing steps, tokens in/out, cost (USD, 4 decimals), elapsed time (live ticking while running; final from `run_done`/pack stats).
8. Other ids required (interface with the capture task, do not rename): chat input `chat-input`, send button `chat-send`, starters `starter-halden`, `starter-brightmoor`, `starter-kettle`.
9. Errors: API unreachable → friendly inline error with retry; a stream that ends without `run_done` → "The run ended unexpectedly" state; malformed events are skipped safely (validate with the contract zod schema; show an unobtrusive notice).

## Engineering
- Next.js App Router, Tailwind v4, TypeScript strict. Keep components small: SSE reader (fetch + ReadableStream parser; EventSource can't POST) as a hook with unit tests, an event reducer (pure function: events → timeline/agents/briefing state) with thorough tests driven by contract fixtures, citation rendering, source panel, stats.
- The reducer must handle interleaved events from parallel agents and out-of-order arrival safely (ordering by `seq` within a run).
- vitest tests (offline, in `pnpm check`): reducer, SSE parser (chunk boundaries splitting frames/UTF-8, keep-alive comments), citation tokenisation, rendering tests of the briefing and timeline components (use `@testing-library/react` + `jsdom` if added), source panel states. `pnpm --filter @mpa/web build` must succeed.
- Perf: first paint fast, no layout jumps while streaming.

## Acceptance
- `pnpm check` green (offline), `pnpm --filter @mpa/web build` succeeds.
- `make dev` with `LLM_MODE=replay` serves the UI; you may run the dev servers and click through manually with the ids above, but do NOT record or commit recordings/screenshots/GIFs. If recordings are not yet in `data/recordings/`, drive the UI with a small mock SSE server of your own under `apps/web/tests/` (fixtures from the contract) for manual checks.
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

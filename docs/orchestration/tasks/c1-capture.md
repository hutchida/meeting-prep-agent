# Task c1-capture — Gate 1: shared Playwright screen-capture package

Target wall time: about 40 minutes. No LLM calls.

## Goal
`packages/capture` is the ONE shared screen-capture helper. Features supply steps; nobody writes a private browser harness. It takes a list of steps and outputs screenshots and an animated GIF into `docs/media/`, and it can run the demo path against the live app (used later in Gate 2 and Rehearsal).

## Owned files
- `packages/capture/**`
- `docs/orchestration/reports/c1-capture.md`

Must NOT touch: anything else (`apps/**`, `agent/**`, `packages/contract/**`, `docs/media/**` contents other than what your own selftest writes under a temp dir, `Makefile`, root config). You may add dependencies to `packages/capture/package.json` only (`playwright`, `gifenc`, `pngjs` or equivalents) and commit `pnpm-lock.yaml`.

## Deliverables
1. **Step DSL** (typed, in `src/steps.ts`): `goto(path|url)`, `click(target)`, `fill(target, text)`, `press(key)`, `toggle(target, on?)`, `waitForText(text|regex, {timeoutMs})`, `waitForTestId(id, {timeoutMs})`, `waitForNoTestId`, `wait(ms)`, `screenshot(name, {fullPage?})`, `expectVisible/expectText(...)` (a step that fails the run when the assertion fails), `mark(label)` (records the elapsed time since start under a label), `note(text)`. `target` accepts `{testId}`, `{text}`, `{role,name}` or `{css}`; prefer `data-testid`. Each step has a name and an optional per-step timeout; failure messages include the step name, the target, a screenshot path of the failed state and never any env values.
2. **Runner** (`src/capture.ts`): `runCapture({ name, baseUrl, steps, outDir = "docs/media", viewport = {1280, 800}, gif = true, gifFrameDelayMs, headless = true, totalTimeoutMs }) → { ok, screenshots[], gif?, marks, durationMs, failedStep? }`. Uses Playwright Chromium. Captures a frame after every step (and on `screenshot` steps a named PNG at `docs/media/<name>-<n>-<label>.png`), then assembles an animated GIF `docs/media/<name>.gif` with a pure-JS encoder (`gifenc` + `pngjs` or similar; **no ffmpeg dependency**), downscaled to ≤ 960 px wide with a size cap (target < 4 MB; reduce colours/frames if exceeded). Deterministic file names; overwrite existing files. Creates `outDir` if missing.
3. **CLI**: `pnpm --filter @mpa/capture run capture -- <script.ts|name> [--base http://localhost:3000] [--out docs/media] [--no-gif] [--headed]` loads a script module that default-exports `{ name, steps, baseUrl? }` and runs it; prints a summary table (step, ms, status) and exit code 0/1. Scripts live in `packages/capture/scripts/*.ts`.
4. **Demo script** `packages/capture/scripts/demo.ts` implementing demo steps 1–5 below against these exact test ids (these ids are an **interface**: the web task (I1) implements them; do not change them without telling the master):

   | Element | `data-testid` |
   |---|---|
   | chat message input | `chat-input` |
   | send button | `chat-send` |
   | starter prompt buttons | `starter-halden`, `starter-brightmoor`, `starter-kettle` |
   | step timeline container | `step-timeline` |
   | one timeline row | `timeline-event` (attributes `data-type` = AgentEvent type, `data-agent` when present) |
   | briefing container | `briefing` |
   | each of the 7 sections | `section-meeting_at_a_glance`, `section-client_snapshot`, `section-recent_news`, `section-where_we_left_off`, `section-open_items`, `section-attendees`, `section-talking_points_and_risks` |
   | an inline citation | `citation` (attribute `data-cite="email:E123"`) |
   | source side panel | `source-panel` (and `source-panel-close`) |
   | "Simulate news outage" toggle | `toggle-news-outage` |
   | run stats | `run-stats` |

   Steps: (1) `goto /`, expect 3 `starter-*` buttons; (2) click `starter-brightmoor` (text: "Prep me for my meeting with Brightmoor on Thursday"), wait for `step-timeline` and a `timeline-event` with `data-type=plan`, then ≥ 4 distinct `data-agent` values among `subagent_started` rows; (3) wait for `briefing` and all 7 `section-*` within 10 s of the click (use `mark` and fail if > 10 s in replay mode; the limit is a script option `maxBriefingMs`, default 10000); (4) click the first `citation`, expect `source-panel` visible with non-empty text, screenshot, close it; (5) turn on `toggle-news-outage`, rerun the same prompt, expect timeline rows with `data-type=retry` and `subagent_failed`, `section-recent_news` text containing "could not be reached", and the other six sections still rendered; screenshots at each major point. The whole script must finish in < 60 s in replay mode. Provide `--base` override and a `--live` option that raises `maxBriefingMs` to 90000.
5. **Self-test without the app**: a tiny static HTML fixture page + a local `http.createServer` in tests that mimics the test-id contract, so `pnpm check` can test the DSL and the runner. The browser-driven tests run only if Chromium is installed (`playwright` browser present); otherwise they are skipped with a clear message (set `RUN_BROWSER_TESTS=1` to force). Unit tests (always run): step DSL types and validation, target resolution, GIF assembly from synthetic PNG frames (frame count, dimensions, size cap, valid GIF header), file naming, error redaction, script loading. Add `pnpm --filter @mpa/capture run install-browsers` (wraps `playwright install chromium`) and document it in `packages/capture/README.md` (a short README is fine; the project README belongs to another task).

## Acceptance
- `pnpm check` green, offline (without Chromium installed it must still pass).
- Run the browser self-test once locally (install Chromium) and report the result: screenshots + GIF produced from the fixture page into a temp dir, time taken, GIF size.
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

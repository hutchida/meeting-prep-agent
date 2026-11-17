# Merge report: g0c-assemble
- Model(s): github-copilot/claude-sonnet-5.5 (opencode worker)
- Wall time start→ready: 2026-11-17T10:00:20Z → 2026-11-17T10:08:17Z (about 8 minutes); active time: unavailable
- Tokens in/out: unavailable
- Cost: unavailable
- Bottlenecks: none blocking. `findLast`/`findLastIndex` are not in the root `lib` (ES2022), so `assemble.ts` avoids them. A first draft of the Halden pack listed gaps in the wrong order; the new vitest test caught it. The secrets grep (`sk-`) matches "risk-scoring" in fixture text (false positive, no secrets).
- Checks run + results:
  - `pnpm install`, `cd agent && uv sync` → ok
  - `pnpm check` (eslint, ruff, tsc, mypy --strict, vitest 153 tests, pytest 246 passed + 1 skipped for the missing Enron corpus) → green, offline
  - `pnpm schema:export` and `uv run python scripts/gen_models.py` run twice → no further diff (also enforced by the existing drift tests)
  - `git diff --cached | grep -i -E "sk-|proxy-host|Bearer "` → only "risk-scoring" false positives
- What was built:
  - `assemblePack` in `packages/contract/src/assemble.ts`, and `assemble_pack` in `agent/src/mpa/contract/assemble.py`, exported from `@mpa/contract` and `mpa.contract`. Both also export `PackAssemblyError` and `checkEventOrder` / `check_event_order`. Python also accepts dicts and unwrapped event models.
  - `packages/contract/fixtures/runs/`: 3 event streams (`run.brightmoor.normal` 49 events with an interleaved retry, `run.brightmoor.news_down` 47, `run.halden.budget_hit` 41), the 3 expected `*.pack.json`, and `assemble_cases.json` (18 assemble cases, 12 order cases, shared by both languages). Ids and meeting data are checked against `data/` by a pytest.
  - Tests: `packages/contract/tests/assemble.test.ts`, `agent/tests/test_contract_assemble.py`, including a TS-vs-Python parity test (pytest runs `scripts/assemble-cli.ts` through tsx over all streams and cases and compares results; skipped only if `pnpm install` has not run).
  - `packages/contract/EVENTS.md` (event order, meaning, UI rendering, assemble usage).
- **Contract changes (exact):**
  1. `PlanEvent` gains two optional fields that must always be sent: `meeting_title` (string, 1..200) and `meeting_start` (ISO UTC timestamp). The title and start are needed for `BriefingPack.meeting` and cannot be derived. `assemblePack` raises `PackAssemblyError` when either is missing. Updated: `src/events.ts`, `schema/AgentEvent.json`, generated `models.py`, `fixtures/AgentEvent.plan.json`.
  2. No other schema, event, interface or `Settings` change. `DraftEvent` doc comment now describes D9. `BriefingPack`, `Gap` and all enums are unchanged.
  - **For downstream tasks:** the orchestrator (S1) must put `meeting_title` and `meeting_start` (from `CalendarEvent.title` / `.start`) on the `plan` event, emit the D9 order, and emit only verified sentences in `draft`s. The API (S3) streams events unchanged. The UI and evals (S4) call `assemblePack` / `assemble_pack`.
- Assemble rules fixed here (not stated in D9): agent→gap source is correspondence=email, documents=docs, news=news, attendees=contacts. `budget_hit` adds one `budget` gap per planned agent with no `subagent_done`/`subagent_failed`, with detail "<budget> budget hit before <agent> finished". With no `run_done` and no `budget_hit`, unfinished agents get an `error` gap "run ended before <agent> finished". If every agent finished but `run_done` is missing, the pack is partial with no gap (no source can be named). Missing sections are filled with empty sections only for incomplete streams (no `run_done`, no `complete` draft); otherwise `PackAssemblyError`. Derived stats (no `run_done`): steps = number of `tool_call`s, tokens/cost 0, duration = last ts − first ts.
- Known gaps / follow-ups:
  - Older fixtures (`BriefingPack.full.json`, `AgentEvent.draft.json`) still use some ids that do not match `data/` (for example Maya as P5). They are schema-only fixtures and untouched.
  - `PlanEvent` fields are optional in the schema (additive), so only `assemblePack` enforces them; consider making them required in a later contract revision.
  - The fixtures were produced by a one-off generator that is not committed; they are hand-authored data now.

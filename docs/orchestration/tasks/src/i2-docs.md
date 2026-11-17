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

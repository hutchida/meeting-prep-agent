# Build notes

## What was built
A hand-built multi-agent meeting-prep system. A chat UI (Next.js) streams a run from a FastAPI service over SSE. The orchestrator resolves the client and meeting from the calendar relative to `DEMO_NOW`, plans, runs four sub-agents in parallel (Correspondence, Documents, News, Attendees; each its own hand-written tool-use loop over a read-only `DataSource`), then a Writer and a cite-or-drop Verifier. The result is a seven-section briefing in which every factual sentence cites a real source item; clicking a citation opens the source.

- `packages/contract`: zod schemas → JSON Schema → generated Pydantic, fixtures, size limits, `assemble_pack` (TS + Python parity).
- `agent/`: LLM client (LiteLLM proxy, replay, record), loop, orchestrator, sub-agents, guardrails (verifier, injection screening, budgets, fault injection), BM25 data layer with a Graph stub, API, optional Langfuse tracing, evals.
- `data/`: fictional dataset (3 clients, 67 synthetic emails, chats, docs, calendar, contacts, news, one injection email) plus a 350-email Enron noise sample, reproducible offline from a committed cache; `data/recordings/` replay set for the demo.
- `packages/capture`: shared Playwright steps + GIF; the demo script runs steps 1–5 in replay in about 14 s.
- `evals/`: hand-written gold briefings and fact/trap lists, judge prompts, results.

Run it: `make setup && make demo` (offline replay), `make dev` (live with `.env`), `make test`, `make eval`.

## Decisions
See `DECISIONS.md` (D1–D16). The ones that matter most: no Haiku alias exists on the proxy so the default is `vertex-ai-gemini-3-flash-preview` (D2, D7); the final pack is rebuilt from events (D9); replay keys are request hashes (D14).

## What's weak
- Fact recall is 77–86 % on the live eval (one run per client, plus or minus about 10 points); "latest state" and informal-chat facts are often only partial, and a planted conflict is occasionally stated one-sidedly (one of the five eval runs involving it; 0 of 10 in a later dedicated check after the D17 fix). The judge is now a stronger model (Sonnet-5, D18) but has not been calibrated against human labels.
- The Verifier's support check is a deterministic heuristic (content words, numbers, dates) with a model check for borderline sentences; it can drop good synthesis sentences and can pass loosely paraphrased ones.
- The model is non-deterministic: live runs differ, and replay is exact only for recorded requests. `make record` handles the prefix-sharing problem and gates quality (D19), but recordings still break on any prompt, data or model change.
- Meeting resolution is rule-based (client alias, weekday, next 14 days), no free-form dates like "tomorrow".
- Fake data only, English only, single user, no auth; the Microsoft Graph source is a stub.
- `Stats.steps` counts model calls, not tool calls. The Langfuse stack was verified by a worker but is not part of CI. Docker, the web UI in a real browser at other sizes and accessibility were only lightly checked.
- Enron items keep their original dates and real corporate addresses (public CMU release) as unrelated noise.

## What next
1. `GraphDataSource` (read-only Mail/Calendar/Files/Chat scopes) behind the existing interface.
2. Self-hosted model via vLLM behind `LLMClient`.
3. An MCP server exposing "prepare briefing" and source lookup.
4. A larger gold set, several runs per eval cell with confidence intervals, and human labels to calibrate the judge; multi-turn follow-ups.
5. Streaming Writer and per-section regeneration; calendar parsing for relative dates.

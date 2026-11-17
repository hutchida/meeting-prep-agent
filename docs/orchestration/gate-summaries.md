# Gate summaries (informational; sent to the user in the session transcript and kept here)

## Gate 0 — Scaffold + Contract (merged, main green)
**Measurements** (full tables in `measurements.md`)
- LiteLLM proxy: 19 aliases, **no Claude Haiku alias** (D2/D7). Chosen default `LLM_MODEL=vertex-ai-gemini-3-flash-preview`: forced tool call works, ~1.4–1.8 s per call, ≈US$0.50/$3.00 per 1M tokens in/out (cost reported per call in `x-litellm-response-cost`); 6 concurrent calls fine, no rate-limit headers. Fallback `vertex-ai-gemini-3.6-flash`. Several models reject `temperature=0` (client omits it); Gemini 3 thinking tokens count against `max_tokens`.
- Enron (CMU) download: 12.4 min, 3 GB extracted (gitignored under `data/raw/`); 350 emails sampled.
**Dataset**: 417 emails (67 synthetic + 350 Enron noise), 28 chats, 21 docs, 9 calendar events, 13 contacts, 26 news items; 3 clients (Halden Pay Wed 11 Mar, Brightmoor Renewables Thu 12 Mar, Kettle & Crumb Fri 13 Mar 2026; `DEMO_NOW` = Mon 9 Mar 2026), each with a contradiction, an unkept promise and a deadline, same-name-company news traps, and an injection email in Halden Pay. Generation cost ≈US$0.07 (141 proxy calls), reproducible offline from a committed cache.
**Contract**: 15 JSON Schemas (zod → JSON Schema → generated Pydantic), 44 valid + 23 invalid fixtures, size limits tested in TS and Python, `assemble_pack` in both languages, 3 full run event streams.
**Checks**: `pnpm check` green offline in ~12 s (246 pytest, 153 vitest).
**Cost so far**: G0b US$2.95, G0c US$0.99 (harness-reported), orchestrator session US$1.36 at last read.

## Gate 1 — Service (merged, main green)
- Merged: S2 data (BM25; build 42 ms, search < 1 ms), C1 capture, S4 evals, S3 API (+Langfuse compose, verified by the worker), S1 core, plus two follow-ups (S4b live evals, S1b quality pass).
- **Gate check**: `pnpm check` ≈ 25 s offline (633 pytest, vitest); `/health` 1–2 ms; first SSE event < 0.2 s; replay run 1.1–1.9 s (offline, no key); live run 15–27 s and US$0.029–0.039 per briefing (limits: 60 s, US$0.05); `make eval` live on all 3 clients 34 s (limit 5 min); failure scenarios (news_down, empty_client, injection, budget_hit) all pass; injection email never obeyed or repeated.
- **Eval (live, vertex-ai-gemini-3-flash-preview, judge same model)**: fact recall 73 / 86 / 86 % (avg 82 %), citation accuracy avg 98 %, 3 hallucinations total, injection resisted on all. Honest weaknesses: dispute on go-live date not flagged in one Halden run; "latest state" facts often partial.
- Recordings: 47 files, 1.1 MB in `data/recordings/` (3 clients normal + Brightmoor news outage); scanned: no URLs/keys/headers.
- Cost so far (harness-reported): G0b 2.95, G0c 0.99, S1 4.83 (+S1b), S2 0.50, S3 1.35 (+0.2), S4 2.45 (+0.47), C1 0.81, orchestrator ≈ 2. Running total ≈ US$18 of ~$50.

## Gate 2 — Interface (merged, main green) and Rehearsal
- I1 web (chat UI, SSE timeline, citations, source panel, outage toggle, stats; 61 tests) and I2 docs (README with real eval numbers, architecture/guardrails/evals docs) merged. `pnpm check` green (637 pytest, 249 vitest).
- Demo steps 1–5 via `packages/capture`: replay twice in 14.3 s and 13.8 s (briefing 5.5 s after click, limit 10 s; whole run limit 60 s), live once in 37.5 s. Screenshots and GIF in `docs/media/` (live in `docs/media/live/`), linked in the README; `docs/demo.md` written.
- Rehearsal issues fixed in place: cold-start hydration race (capture waits for network idle), dev overlay in screenshots (new `make demo` uses the production web build), outage screenshot showed the previous run (fresh chat before step 5), and the recorded Brightmoor briefing had an empty "Talking points" section (re-recorded with quality criteria; `test_demo_replay.py` guards it).

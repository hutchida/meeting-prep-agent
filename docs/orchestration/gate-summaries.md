# Gate summaries (informational; sent to the user in the session transcript and kept here)

## Gate 0 — Scaffold + Contract (merged, main green)
**Measurements** (full tables in `measurements.md`)
- LiteLLM proxy: 19 aliases, **no Claude Haiku alias** (D2/D7). Chosen default `LLM_MODEL=vertex-ai-gemini-3-flash-preview`: forced tool call works, ~1.4–1.8 s per call, ≈US$0.50/$3.00 per 1M tokens in/out (cost reported per call in `x-litellm-response-cost`); 6 concurrent calls fine, no rate-limit headers. Fallback `vertex-ai-gemini-3.6-flash`. Several models reject `temperature=0` (client omits it); Gemini 3 thinking tokens count against `max_tokens`.
- Enron (CMU) download: 12.4 min, 3 GB extracted (gitignored under `data/raw/`); 350 emails sampled.
**Dataset**: 417 emails (67 synthetic + 350 Enron noise), 28 chats, 21 docs, 9 calendar events, 13 contacts, 26 news items; 3 clients (Halden Pay Wed 11 Mar, Brightmoor Renewables Thu 12 Mar, Kettle & Crumb Fri 13 Mar 2026; `DEMO_NOW` = Mon 9 Mar 2026), each with a contradiction, an unkept promise and a deadline, same-name-company news traps, and an injection email in Halden Pay. Generation cost ≈US$0.07 (141 proxy calls), reproducible offline from a committed cache.
**Contract**: 15 JSON Schemas (zod → JSON Schema → generated Pydantic), 44 valid + 23 invalid fixtures, size limits tested in TS and Python, `assemble_pack` in both languages, 3 full run event streams.
**Checks**: `pnpm check` green offline in ~12 s (246 pytest, 153 vitest).
**Cost so far**: G0b US$2.95, G0c US$0.99 (harness-reported), orchestrator session US$1.36 at last read.

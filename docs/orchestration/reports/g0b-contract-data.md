# Merge report: g0b-contract-data
- Model(s): github-copilot/claude-sonnet-5.5 (worker, via opencode). Data prose: the proxy's `vertex-ai-gemini-3-flash-preview`.
- Wall time start→ready: 2026-11-17T09:27:45Z → 2026-11-17T09:59Z (about 31 min including the interfaces addendum); active time: unavailable
- Tokens in/out: unavailable (worker harness); data generation used 141 LLM calls (about 0.07 USD as reported by the proxy)
- Cost: data generation 0.0727 USD (final run) plus an earlier discarded run and the measurement calls, a few cents each, not individually recorded. Total well under the US$3 budget.
- Bottlenecks: Enron download 12.4 min (ran in the background, so no wait); Gemini 3 "thinking" tokens ate `max_tokens` and truncated the first generation run (fixed with `reasoning_effort: minimal`, which also made calls faster and cheaper); first phone-number redaction regex missed `ph.(713) 348-3733` and numbers split across a newline (found by the dataset test, fixed); the generated `models.py` initially inlined union schemas, so root names were added by `gen_models.py`.
- Checks run + results:
  - `pnpm check` → green (190 pytest, 102 vitest, eslint, tsc, ruff, mypy strict), about 20 s
  - `pnpm check` with `.env` and `data/raw` moved away (CI-like, offline) → green (1 skip: raw re-sample test)
  - `pnpm --filter @mpa/contract run schema:export` then `git status` → no diff (idempotent)
  - `cd agent && uv run python scripts/gen_models.py` → no diff (idempotent); `--check` is also run inside pytest
  - `cd agent && uv run python scripts/generate_data.py --offline` (with and without `--no-raw`) → byte-identical to committed data (also a pytest)
  - Secret scan from the task (tracked files, and the files this branch touches) → prints nothing for files I touched; the only hits are pre-existing task-prompt text under `docs/orchestration/tasks/`. The real key and URL values grepped against tracked files → 0 matches
  - Repo data size: `emails.jsonl` 0.65 MB, everything else about 0.1 MB, cache 0.12 MB (well under 6 MB)
- What was built:
  - `packages/contract`: zod 4 schemas for all named entities, JSON Schema export (`schema:export`, draft 2020-12, self-contained `$defs`), 15 schemas, 44 valid + 23 invalid fixtures, `citation_cases.json`, vitest tests (freshness, zod + ajv for every fixture, size limits, citation helpers, timestamp format)
  - `agent/src/mpa/contract`: generated `models.py` (datamodel-code-generator, `extra="forbid"`), `limits.py`, `citations.py`, `interfaces.py` and `settings.py` (the addendum, verbatim from `docs/orchestration/interfaces.md`), all re-exported from `mpa.contract`
  - `agent/scripts/gen_models.py`, `sample_enron.py`, `generate_data.py` (+ `_gen_llm.py`, `_gen_plot.py`)
  - `data/`: 417 emails (67 synthetic + 350 Enron), 28 chats, 21 docs, 9 calendar events, 13 contacts, 26 news items, `PLOT.md` (with a machine-readable JSON block incl. per-client item ids), `README.md`, committed LLM cache, `recordings/.gitkeep`
  - Python tests: schema/model property-set equality, fixtures under JSON Schema + Pydantic, unknown keys rejected, limits, citation parity, dataset validation, offline reproduction, interfaces/Settings
  - `docs/orchestration/measurements.md`
- Known gaps / follow-ups:
  - **Recommended `LLM_MODEL=vertex-ai-gemini-3-flash-preview`** (fallback `vertex-ai-gemini-3.6-flash`). It is `Settings.from_env` default.
  - LLMClient must omit `temperature` for `azure/gpt-5*`, `vertex-ai-claude-sonnet-5` and `vertex-ai-claude-opus-4.8` (HTTP 400 otherwise) and use a generous `max_tokens` for Gemini 3 (thinking counts); `reasoning_effort: minimal` removes the thinking cost where acceptable.
  - Tool-call reliability was judged from 8 forced single calls + 6 concurrent ones only.
  - "A field present only in a mapping fails CI": there is no hand-written mapping; the equivalent guarantees (fixtures, Pydantic and JSON Schema share one property set; models regenerate from schema) are tested.
  - Enron items keep their original 1999-2002 dates and real corporate addresses (public release); only synthetic items obey the three-month window and `.test` domains.
  - `data/raw/` (3 GB extracted) stays on the machine, gitignored; CI never needs it (committed Enron lines are reused).
  - Spec deviations in `interfaces.py`: only added the missing imports (`mpa.contract.models` types, `Settings`); names and signatures are unchanged. `Settings.recordings_dir` defaults to `<repo>/data/recordings` regardless of `MPA_DATA_DIR`, as written in the spec. `from_env` raises `ValueError` on invalid values. `subagent_timeout_s` has no env var (not listed).

## Decisions for DECISIONS.md (master to record)
1. **Timestamps:** one canonical format, `YYYY-MM-DDTHH:MM:SS[.sss]Z` (UTC, `Z` only, ASCII digits). Offsets like `+00:00` are rejected by schema; `DEMO_NOW` in `.env` is parsed by `Settings` and normalised to UTC.
2. **Email address field is `sender`** (not `from`, a Python keyword); addresses are plain strings, `to`/`cc` are string lists.
3. **`draft` event carries `sections` (1 to 7 `BriefingSection`s) and `complete`**, not the whole pack: a full `BriefingPack` can be 40 KB and an event is capped at 8 KB. The finished pack must be served another way (for example `GET /briefings/{run_id}`); the S3 API task needs to expose it.
4. **`ToolResult` is `{items, total_matches, truncated}`.** `items` mixes `SearchHit` (search tools) and `SourceItem` (get tools). A `get_email` result for a body over 4 KB must be truncated by the tool layer with `truncated: true` because tool items are capped at 4 KB while emails may be 6 KB. The 10-item and 4 KB limits are enforced by `assertWithinLimit` / `assert_within_limit`, not by the JSON Schema (`maxItems` 10 is in the schema).
5. **Citations and search hits are one object per type** (`CitationEmail`, ... `SearchHitCal`) so the id prefix is enforced by the schema. Pack sections are a fixed 7-tuple (JSON Schema `prefixItems`) so order and ids are enforced by schema, not only by code.
6. **Sentences:** `FactSentence` (>=1 citation, optional `kind: "fact"`) or `NoteSentence` (`kind: "note"`, citations optional). `SubAgentOutput.findings` uses the same `Sentence` type.
7. **Generated `models.py` is formatted with the repo's ruff settings and carries `# ruff: noqa`**; regenerate with `uv run python scripts/gen_models.py`. Union-only schemas (`Citation`, `SearchHit`, `SourceItem`) are added as `RootModel` classes by the script.
8. **Dataset generation:** LLM cache key excludes the model name (so `--offline` works in CI without `.env`), uses `temperature=0`, `seed`, `reasoning_effort=minimal`; the Enron sample is re-sampled from `data/raw` when present, otherwise re-used from `data/emails.jsonl`.
9. **New dev dependencies:** `datamodel-code-generator` (agent), `tsx` and `ajv` (contract package).

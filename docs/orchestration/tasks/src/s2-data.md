# Task s2-data — Gate 1: Data access (DataSource, FakeDataSource with BM25, GraphDataSource stub)

Target wall time: about 35 minutes. No LLM calls anywhere in this task (everything is offline and deterministic).

## Goal
Implement the `DataSource` interface (see `docs/orchestration/interfaces.md` and `agent/src/mpa/contract/interfaces.py`, merged on `main`) over the committed fake dataset in `data/` with BM25 retrieval, plus a Graph stub.

## Owned files
- `agent/src/mpa/data/**`
- `agent/tests/test_data_source*.py` (prefix new test files with `test_data_source`)
- `docs/orchestration/reports/s2-data.md`

Must NOT touch: contract (`packages/contract/**`, `agent/src/mpa/contract/**`), `data/**` (the dataset is read-only to you), `agent/src/mpa/{llm,loop,agents,guardrails,api,tracing,evals}/**`, `apps/**`, `evals/**`, `Makefile`, root config. `agent/pyproject.toml`: additive deps only (`rank-bm25` is already there).

## Inputs (already merged on main)
- `data/README.md` (layout and ID scheme), `data/{emails,chats,docs,calendar,contacts,news}.jsonl`, `data/PLOT.md` (ground truth: key facts and the source ids that prove them; use it to write retrieval-quality tests).
- Pydantic models in `agent/src/mpa/contract/models.py` (`Email`, `ChatMessage`, `Doc`, `CalendarEvent`, `Contact`, `NewsItem`, `SearchHit`, `SourceItem`), `DataSource`, `DataSourceError`, `Settings` in `mpa.contract`.
- Fixtures `packages/contract/fixtures/` (shape reference).

## Deliverables
1. `mpa/data/fake.py`: `FakeDataSource(data_dir: Path)` implementing every method of the `DataSource` protocol exactly as written in the interfaces spec (all async; `KeyError` for unknown ids; search methods return ≤ `limit` (≤ 10) `SearchHit` with the contract's shape, each ≤ 4 KB serialised, e.g. id, type, title, snippet (≤ ~240 chars around the best match), score). `get_calendar(start, end, query)` filters by time window and/or text (title, description, attendee names). `find_contacts(query)` searches contacts by name/org/role. `get_source(type, id)` returns the right `SourceItem` for any of the six citation types.
2. Retrieval: BM25 (`rank_bm25.BM25Okapi`), one index per item type, built lazily once and cached; tokenisation lowercases, strips punctuation, keeps numbers, drops a small stopword list; field weighting (e.g. subject/title repeated) is fine; ties broken deterministically (by id). Enron noise (`origin == "enron"`) must not outrank relevant synthetic items for client queries: verify with tests; if BM25 alone lets noise in, down-weight it deterministically and say so in the report. Index build for the full dataset < 1 s; a search < 50 ms.
3. `mpa/data/graph.py`: `GraphDataSource` stub: every method raises `NotImplementedError("...")` and the class docstring explains the intended Microsoft Graph mapping (read-only, delegated permissions: `Mail.Read` → email, `Chat.Read`/`ChatMessage.Read` → chat, `Files.Read.All` → docs, `Calendars.Read` → calendar, `People.Read`/`Contacts.Read` → contacts; news via a web-search provider; pagination and throttling (429 Retry-After) notes; no write scopes ever).
4. `mpa/data/__init__.py`: `build_data_source(settings) -> DataSource` (`snapshot` → `FakeDataSource(settings.data_dir)`, `graph` → `GraphDataSource()`), exporting `DataSource`, `DataSourceError`, `FakeDataSource`, `GraphDataSource`.
5. Fault tolerance of the loader: a malformed jsonl line raises a clear error naming file and line number (never silently skipped). No path, URL or key ever appears in messages beyond relative file names.
6. Tests (offline, fast): protocol conformance (`isinstance`-style check via a runtime-checkable wrapper or type-annotated assignment under mypy), each method happy-path and unknown id, `limit` capping, 4 KB cap on hits, determinism (two instances → identical results), calendar window filtering for `DEMO_NOW` week (three meetings found, correct clients), `get_source` for every type, graph stub raises. Retrieval-quality tests using `data/PLOT.md` facts: for each client and for ≥ 5 realistic natural-language queries (e.g. "Brightmoor renewal budget", "Halden Pay compliance deadline"), the expected source ids appear in the top 5; same-name-company news is not ranked above the client's own news for a client-name query unless the text is genuinely ambiguous (report any ambiguity). Read expected ids from `data/PLOT.md` or hard-code ids verified against the data, but never edit `data/`.

## Acceptance
- `pnpm check` green, offline, no API key.
- Search < 50 ms, index build < 1 s on the committed dataset (assert loosely in a test or report measured numbers).
- Merge report with measured numbers committed to `docs/orchestration/reports/s2-data.md`.

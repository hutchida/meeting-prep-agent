# Guardrails

Each guardrail below lists what it does, where it lives and which offline tests cover it. All tests run with `cd agent && uv run pytest` (part of `make test`) and need no model or key. Test names are given so they can be found with `grep`.

## 1. Cite-or-drop verifier

Where: `agent/src/mpa/guardrails/verifier.py`, `guardrails/support.py`. Runs after the Writer.

- Every fact sentence must carry at least one citation (`no_citation`).
- Each cited id must be one the run actually retrieved or was given (`invalid_citation`) and must exist: the Verifier fetches it through `DataSource.get_source`. A transient read error is retried once, then the sentence is dropped.
- The cited text must support the sentence (`unsupported`). The check in `support.py` is deterministic: amounts, numbers of two or more digits, percentages, clock times and calendar dates in the sentence must appear in the cited text after normalisation (a changed figure is the typical hallucination), and at least half of the remaining content words (stop words removed, crudely stemmed) must appear. Very short sentences must match every word. A calendar citation is also checked against its attendees' names and roles.
- Borderline sentences (figures match, wording is thin) go to one batched model check if the run budget allows; without budget or a usable answer they are dropped.
- Citations that do not share content with the sentence are pruned; the sentence is kept if some citation does.
- Notes (`kind: "note"`) have no factual claim and are exempt. Only the pipeline creates notes, never the model.
- Dropped sentences are counted in `verifier_result` (total, kept, dropped) with up to ten examples (section, reason, text). Only kept sentences are ever emitted as `draft`.

Limits of the check: it is word-overlap, not entailment. It can drop a true sentence that combines several sources, and it passes a true sentence that is cited to the wrong item. The sub-agents also run the same support check on their own findings before the Writer sees them, but only removing findings that clearly fail, so a drop there does not show up in `verifier_result`.

Tests: `tests/test_guardrails_verifier.py` (kept, non-existent id, unsupported with a real citation, no citation, citation outside the allowed set, notes exempt, counts and reasons, injection text, read retry, borderline handling, calendar attendees), `tests/test_guardrails_support.py` (all 24 planted facts in `data/PLOT.md` are supported by their sources; changing a figure fails each of them), `tests/test_agents_writer.py::test_hallucinated_writer_sentences_are_dropped_by_the_verifier`.

## 2. Read-only tool set

Where: `agents/tools.py`. The only tools are `search_email`, `get_email`, `search_chat`, `get_chat`, `search_docs`, `get_doc`, `search_news`, `get_news`, `get_calendar`, `get_contact`, `find_contacts` and the terminal `submit_findings`. Each agent sees only its own subset (`AGENT_TOOLS`). There is no tool that sends, writes, deletes or calls an arbitrary URL, and the `DataSource` interface has no write method.

Tests: `tests/test_agents_tools.py::test_every_tool_is_on_the_read_only_allow_list` (the set of tool names equals the allow-list), unknown tools and bad arguments are tool errors (`tests/test_loop_runner.py`).

## 3. Untrusted data and prompt injection

Where: `loop/tools.py` (wrapping and screening), `guardrails/injection.py` (patterns), `agents/prompts.py` (the system prompt says tool results are third-party data, never instructions), `agents/orchestrator.py` (notes for flagged sources), `guardrails/verifier.py` (drops).

- Every tool result is wrapped in `<untrusted_data tool="...">` and any closing tag inside the data is neutralised.
- Before the model sees a result, string fields are screened. Spans that read like instructions to an assistant (ignore previous instructions, forward all emails, "system:" lines, reveal your prompt, transfer funds and similar) are replaced by `[flagged: instruction-like text removed]` and recorded as flags.
- A flagged source is never cited as fact: sub-agent findings citing it are removed, and the Verifier drops any sentence that cites it, that looks like an instruction, or that repeats an address or a run of five words from a removed span (reason `injection`).
- The briefing then carries a note in "Talking points and risks": "Source E61 contains instructions that were ignored." (cited, `kind: "note"`).
- The dataset has one planted injection, an email in the Halden Pay data (listed in `data/PLOT.md`).

Tests: `tests/test_guardrails_injection.py` (block and sentence patterns; ordinary business text untouched; across the whole dataset only the planted email is flagged; echo detection), `tests/test_loop_runner.py::test_instruction_like_text_is_replaced_and_flagged_before_the_model_sees_it`, `tests/test_orchestrator_scenarios.py::test_prompt_injection_is_not_obeyed_or_repeated` (a mock model that obeys the attack gets its sentences dropped), the `injection` eval scenario (live: the briefing must neither obey nor repeat the attack).

Limits: the patterns are heuristic and English only. A cleverly phrased attack could pass screening; the defence in depth is that tools are read-only, so a successful injection cannot send or change anything, and the Verifier requires every sentence to be supported by cited text.

## 4. Budgets and partial briefings

Where: `loop/budget.py`, `loop/runner.py`, `agents/subagents.py`, `agents/writer.py`. Defaults in `contract/settings.py`: 8 model calls per agent, 80,000 tokens and US$0.05 per run, overridable with `MAX_STEPS_PER_AGENT`, `MAX_TOKENS`, `MAX_COST_USD`.

- `Budget.begin_step` is checked before every model call (agents, Writer, the Verifier's model check). Steps are per agent; tokens and cost are per run.
- On the last allowed step an agent is offered only `submit_findings`.
- The first limit hit emits exactly one `budget_hit` event. The agent in flight salvages up to six findings from items it already retrieved; if there are none it ends with `subagent_failed` (reason `budget`). The Writer runs without a model if the budget is gone. The pack is `partial` with a `budget` gap per affected source and a note in the affected sections.
- The `time` budget kind exists in the contract but is not emitted; time limits are the per-agent timeout (45 s) and the tool timeout (10 s).

Tests: `tests/test_loop_budget.py` (per-agent steps, run-wide tokens and cost, one report, thread safety), `tests/test_loop_runner.py` (forced submit on the last step, budget checked before every call), `tests/test_orchestrator_scenarios.py` (budget hit ends cleanly with named gaps; Writer degrades), eval scenario `budget_hit`.

## 5. Retries, timeouts and failure isolation

Where: `loop/runner.py`, `llm/litellm.py`, `agents/subagents.py`, `agents/orchestrator.py`, `api/sse.py`.

- A tool call that raises `DataSourceError` or times out is retried once after a short deterministic backoff, with a `retry` event. A second failure is returned to the model as an error.
- The model client retries 429, 5xx and timeouts twice with backoff; client errors (4xx) are not retried. Error text never contains the URL or key.
- A sub-agent that times out, crashes or is cancelled becomes `subagent_failed`; the other agents continue.
- A consumer disconnect cancels the producer and all child tasks.
- Any exception in the run produces a valid terminal sequence ending in `run_done` with `partial=true`.

Tests: `tests/test_loop_runner.py` (retry then success; keeps failing; timeout reason), `tests/test_llm_litellm.py` (retries, gives up without leaking URL or key, client errors not retried), `tests/test_orchestrator_scenarios.py` (sub-agent timeout does not stop the others; cancelled or crashing sub-agent is isolated; unexpected bug still ends with a valid stream), `tests/test_api.py` (disconnect cancels the run; run function exceptions become a partial `run_done`).

## 6. Fault injection

Where: `guardrails/faults.py`. `FAIL_SOURCE` (`news`, `email` = email and chat, `docs`, `all`) or the request field `fail_source` wraps the data source seen by the sub-agents in `FaultInjectingDataSource`, which raises `InjectedFault` (a `DataSourceError`) for the chosen sources. The loop reports it as reason `fault_injected`. The UI exposes it as the "Simulate news outage" toggle. Meeting resolution and the Verifier read the unwrapped source on purpose, so the briefing header still works.

Expected result for `news`: two `retry` events, then `subagent_failed` for the News agent, the sentence "News could not be reached; recent news is not included in this briefing.", the other sections complete, `partial=true` with a `news` gap.

Tests: `tests/test_guardrails_faults.py` (only the named sources fail), `tests/test_orchestrator_scenarios.py::test_fault_injection_still_finishes_with_a_partial_briefing` (parametrised over the sources), eval scenario `news_down` (checks retry before failure, the plain statement, no invented news citations, a `news` gap, partial flag, other sections cited).

## 7. Size limits

Where: `packages/contract/src/limits.ts`, `agent/src/mpa/contract/limits.py` (identical values, tested in both languages). `AGENT_EVENT_MAX_BYTES` 8192, `BRIEFING_PACK_MAX_BYTES` 40960, `TOOL_RESULT_MAX_ITEMS` 10, `TOOL_RESULT_ITEM_MAX_BYTES` 4096, `EMAIL_MAX_BYTES` 6144. Size is the UTF-8 length of compact JSON.

- `loop/tools.py` caps tool results (at most 10 items of at most 4 KB; the longest string field is shortened and `truncated: true` is set).
- `EventEmitter` and the API validate every event against the contract and the 8 KB cap. An invalid or oversize event becomes a safe terminal event rather than a broken stream.
- The orchestrator trims trailing fact sentences until each draft event is at most 7,000 bytes and the pack at most 36,000.

Tests: `packages/contract/tests/contract.test.ts` and `tests/test_contract_schemas.py` (valid and `just_under_limit` fixtures pass, `over_limit` fixtures fail), `tests/test_loop_runner.py::test_results_are_capped_at_ten_items_and_4kb_each`, `tests/test_agents_writer.py::test_fit_trims_sentences_to_the_event_and_pack_caps`, `tests/test_api.py` (invalid and oversize events).

## 8. Secrets and safe errors

- `.env` is gitignored; `.env.example` lists names only.
- `RecordingClient` refuses to write a recording that contains the value of `LITELLM_BASE_URL` or `LITELLM_API_KEY` or a key-shaped string (`llm/replay.py`). Replay keys are hashes.
- `LiteLLMClient` strips the URL and key from error text. The API never returns exception text; request logs hold method, path, status and duration only. `tracing/redact.py` truncates content and replaces URLs, bearer tokens, key-like strings and the values of `LITELLM_*` and `LANGFUSE_*` before anything is sent to Langfuse. `/health` reports configuration modes, not values.
- Eval reports are sanitised before writing (`evals/report.py`).

Tests: `tests/test_llm_replay.py::test_recording_refuses_secrets`, `tests/test_llm_litellm.py` (no leak in errors), `tests/test_tracing.py::test_content_is_truncated_and_scrubbed`, `tests/test_api.py::test_bad_body_is_422_without_echoing_input` and `test_request_log_has_no_bodies`, `tests/test_evals_report.py` (secret hygiene).

# Evals

Gate-1 evaluation of the briefing agent: hand-written gold briefings, a fact list per client, an LLM judge and failure-scenario checks.

```sh
make eval                                         # all three clients, normal scenario, live model
cd agent && uv run python -m mpa.evals --scenario all --client all --live
cd agent && uv run python -m mpa.evals --scenario news_down --replay
cd agent && uv run python -m mpa.evals --fake --scenario all     # scripted fakes, no model, no key
```

| Path | Contents |
|---|---|
| `gold/<client>.md` | Hand-written 7-section gold briefing with `[type:ID]` citations, checked against `data/*.jsonl` |
| `gold/<client>.facts.json` | Key facts (must appear) and traps (must not be stated as fact), with source ids |
| `prompts/judge_facts.md`, `prompts/judge_claims.md` | Versioned judge prompts (fact recall and traps in one call; hallucination check in one or two) |
| `fixtures/report.golden.md` | Golden file for the report renderer test |
| `results/latest.md`, `latest.json` | Output of the last run (`latest.json` is a list of contract `EvalResult`) |

Scoring: fact recall (yes = 1, partial = 0.5), hallucinations (verifier drops plus judge-flagged unsupported claims, reported separately), citation accuracy (verifier kept over total), steps, tokens, cost, latency, trap violations and injection resistance.
`JUDGE_MODEL` selects the judge model; the default is `vertex-ai-claude-sonnet-5` (a stronger model than the agent's, so the judge does not grade its own work), `JUDGE_MODEL=same` uses `LLM_MODEL`, and replay runs always use `LLM_MODEL`. Hard failures (injection obeyed or repeated as fact, a scenario with no briefing) make the exit code non-zero; `--strict` makes every failed check do so.
`--judge citations` scores recall from cited source ids only (no model call).

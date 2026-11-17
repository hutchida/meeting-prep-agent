# Task s1b-tune — Gate 1: orchestrator quality pass (follow-up to s1-core)

You are continuing task `s1-core` (read `docs/orchestration/tasks/s1-core.md` and `docs/orchestration/reports/s1-core.md`; same ownership: `agent/src/mpa/{llm,loop,agents,guardrails}/**` and their tests). The first honest live eval is on `main` in `evals/results/latest.md` (fact recall 77% / 68% / 82%; citation accuracy 100% / 96% / 88%) and its findings are listed in `docs/orchestration/reports/s4-evals.md` under "Orchestrator findings". Target wall time: 35 minutes. Live LLM spend cap: US$1.50.

## Goal
Raise fact recall and reduce verifier drops through **general** improvements, keeping every Gate-1 target: live run < 60 s and < US$0.05 per briefing, `pnpm check` green offline, all contract rules, no contract changes.

## Findings to address (generic fixes, not data-specific)
1. **Commitments and unkept promises** are summarised away: the Correspondence and Documents agents should explicitly extract "who promised what by when" and whether a later message shows it was delivered; the Writer must carry open commitments into `open_items` and `where_we_left_off` with the date. Add a dedicated step/tool usage hint (for example search for promise language: "will send", "by Friday", "I'll get back", "still waiting", "chase") and make the structured findings carry a `kind` or tag for commitments if the contract's `SubAgentOutput` already allows it (do not change the contract).
2. **Contradictions** between sources must be surfaced as such, with both sides cited, in `talking_points_and_risks` (or `client_snapshot`), instead of picking one side (observed: 165 vs 180 MW stated as settled in one run). Make the Writer prompt and the findings handling detect conflicting figures/dates on the same subject and state "Sources disagree: …" with both citations.
3. **Deadlines and money**: fees, instalments, dates and deadlines found in documents should reliably reach the briefing (`client_snapshot`, `open_items`).
4. **Mis-cited role facts**: attendee role/responsibility sentences must be cited to the contact record (`[contact:P…]`) when the contact says it; instruct the Attendees agent and the Writer accordingly; make the Verifier's support check accept the contact record for such sentences.
5. **Verifier drops** (Kettle & Crumb, 2-3 of ~25 sentences): inspect which sentences are dropped and why (`dropped` in `verifier_result`); fix the cause on the producing side (sentences that paraphrase dates loosely, e.g. "late February" for a specific date) by instructing agents/Writer to copy exact dates/figures from sources. Do not weaken the Verifier's rules.
6. `empty_client` runs report contact lookups that fail as `error` gaps; a missing item should be reported as "no data", not an error gap (keep real errors as errors).

## Rules
- **Do not overfit.** You may read `evals/results/latest.md`, the S4 report and `data/PLOT.md` to understand failure modes, but do NOT copy gold facts, specific names, figures or dates from the dataset/gold into prompts or code. Improvements must be generic (they should help on any client's data).
- Measure: run `cd agent && uv run python -m mpa.evals` (the harness on `main`, ≈ 25 s, ≈ US$0.11 per run including the judge) before and after, three runs each when practical, and report the averages honestly. Run failure scenarios once at the end (`--scenario news_down`, `empty_client`, `injection`, `budget_hit`). If a change lowers recall or breaks a scenario, revert it. Do not edit `evals/**` or the harness (not yours); do not commit `evals/results/**` changes (the master re-runs the official eval after merging).
- Keep prompts deterministic functions of the request + data (replay keys); keep each event ≤ 8 KB and pack ≤ 40 KB; update your unit tests for every behaviour change; keep `pnpm check` green.
- Commit often. Do not commit recordings.

## Acceptance
`pnpm check` green; before/after eval numbers (recall, citation accuracy, hallucinations, cost, latency per client; averages over the runs) in an appended "Tuning pass" section of `docs/orchestration/reports/s1-core.md`, plus what you changed and what you tried that did not help; failure scenarios still pass; then `worker_done`.

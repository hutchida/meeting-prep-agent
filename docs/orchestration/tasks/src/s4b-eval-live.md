# Task s4b-eval-live — Gate 1: live eval runs (follow-up to s4-evals)

You are continuing task `s4-evals` (read `docs/orchestration/tasks/s4-evals.md`, section "Live runs", and `docs/orchestration/reports/s4-evals.md`). The orchestrator (S1), data (S2), API (S3) and capture (C1) are now merged on `main`. Target wall time: 25 minutes. Live LLM spend cap for this task: US$1.50 total (the proxy bills per call; `x-litellm-response-cost` is captured by the client).

## Do
1. In your worktree (branch `s4-evals`) run `git merge main`; run `pnpm install` and `cd agent && uv sync`; `pnpm check` must be green.
2. Wire the harness to the real orchestrator (`mpa.agents.orchestrator.run_briefing`, `mpa.llm.build_llm_client`, `mpa.data.build_data_source`, `mpa.tracing.build_tracer`), fix any integration mismatch that is inside your owned files (`evals/**`, `agent/src/mpa/evals/**`, `agent/tests/test_evals*.py`). Event rules: read `packages/contract/EVENTS.md` and use `assemble_pack`; the pack is rebuilt from events (there is no pack endpoint).
3. Run `make eval` (3 clients, normal scenario, live) and check it finishes in < 5 minutes. Then run each failure scenario once: `cd agent && uv run python -m mpa.evals --scenario news_down|empty_client|injection|budget_hit` (use the client each scenario defines; `injection` on Halden Pay).
4. Calibrate the judge: read a sample of the judge's verdicts against the actual briefing text and gold facts; fix judge-prompt or parsing bugs (inside `evals/prompts/**`, `mpa/evals/**`). Do NOT soften scoring to look good: report honest numbers. If the judge disagrees with your own reading, say so in the report.
5. Commit `evals/results/latest.md` and `evals/results/latest.json` from a real run (no URLs/keys/headers inside; check). The table must contain per-client fact recall, hallucinations, citation accuracy, steps, tokens, cost, latency, injection result, plus the failure-scenario pass/fail table.
6. Do NOT edit S1/S2/S3 code. If an eval fails because of an orchestrator problem, record the symptom precisely (client, scenario, event excerpt, expected vs actual, run count) in your report under "Orchestrator findings" so the master can route it.
7. Update `docs/orchestration/reports/s4-evals.md` (append a "Live runs" section: commands, wall time, per-client numbers, cost of the eval run, failures). Commit, then `worker_done`.

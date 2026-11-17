# Orchestration status

Updated by the master session. Run: `run_51fb09e2ed13`. Workers: opencode + `github-copilot/claude-sonnet-5.5`. Harness-reported cost per task is in each `reports/<id>.md`.

| Gate | Task | Branch/worktree | State | Notes |
|------|------|-----------------|-------|-------|
| G0a | scaffold | main | merged | `pnpm check` green, `make dev` serves /health + placeholder page |
| G0b | g0b-contract-data | g0b-contract-data | merged | 31 min, US$2.95 |
| G0c | g0c-assemble | g0c-assemble | merged | 8 min, US$0.99; closed the final-pack delivery gap (D9) |
| G1 | s2-data | s2-data | merged | 5 min, US$0.50 |
| G1 | c1-capture | c1-capture | merged | 14 min, US$0.81 |
| G1 | s4-evals | s4-evals | merged (offline part) | 16 min, US$2.45; live runs deferred until S1 lands (follow-up s4b) |
| G1 | s3-api | s3-api | merged (+ follow-up: mypy unused ignore) | 17 min, US$1.35; Langfuse compose verified by the worker |
| G1 | s1-core | s1-core (ctx_82dc0a9f06a8) | running | tests/live trials; last commit 10:34Z |
| G2 | i1-web, i2-docs | - | prompts written | start after Gate 1 check |

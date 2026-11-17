# Orchestration status

Updated by the master session. Run: `run_51fb09e2ed13`. Workers: opencode + `github-copilot/claude-sonnet-5.5`.

| Gate | Task | Branch/worktree | State | Notes |
|------|------|-----------------|-------|-------|
| G0a | scaffold | main | done | `pnpm check` green, `make dev` serves /health + placeholder page |
| G0b | g0b-contract-data | g0b-contract-data | running (dispatch ctx_26f2b7ffd7cb) | 3+ commits; interfaces addendum sent |
| G1 | s1-core, s2-data, s3-api, s4-evals, c1-capture | - | prompts written | start after G0b merged and main green |
| G2 | i1-web, i2-docs | - | prompts written | start after Gate 1 check |

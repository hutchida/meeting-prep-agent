# Orchestration report

Build of `meeting-prep-agent`, orchestrated from one opencode session inside Orca (run `run_51fb09e2ed13`). Wall clock: 09:21 → ~11:45 UTC on 2026-11-17 (about 2 h 25 min). All workers: opencode agent, `github-copilot/claude-sonnet-5.5`. Costs are harness-reported (`opencode session export`), not estimated. Application LLM calls (the agent under test) go to the LiteLLM proxy with `vertex-ai-gemini-3-flash-preview`.

## Per task

| Gate | Task | Wall | Output tokens | Cost (harness) | Notes |
|---|---|---|---|---|---|
| 0a | scaffold (master) | ~15 min | in master session | in master total | pnpm workspaces, uv, CI, Makefile |
| 0b | g0b-contract-data | 31.2 min | 109,625 | US$2.95 | contract, Pydantic mirror, dataset, measurements, interfaces |
| 0c | g0c-assemble | 8.2 min | 42,512 | US$0.99 | `assemble_pack` TS+Py, run fixtures (gap found at Gate 0) |
| 1 | s2-data | 4.7 min | 25,958 | US$0.50 | BM25 `FakeDataSource` |
| 1 | c1-capture | 14.0 min | 42,303 | US$0.81 | Playwright steps + GIF |
| 1 | s3-api | 17.1 min | 56,888 | US$1.35 | FastAPI SSE, Langfuse; + follow-up (mypy ignore, small, not metered separately) |
| 1 | s4-evals (offline) + s4b (live) | 15.8 + 11.4 min | 81,673 + 15,018 | US$2.45 + 0.47 | gold files, judge, harness, scenarios |
| 1 | s1-core + s1b tuning | 36.4 + 16.5 min | 125,098 + 30,260 | US$4.83 + 1.05 | the agent stack, then a quality pass |
| 2 | i1-web | 9.8 min | 46,209 | US$0.86 | chat UI |
| 2 | i2-docs | 7.6 min | 35,028 | US$0.89 | README + docs |
| – | master (this session) | 141 min | 95,974 | US$3.90 | scaffold, prompts, merges, recordings, rehearsal |
| | **Total harness cost** | | | **≈ US$21.0** | |

Application-side LLM spend through the proxy (per-call costs reported by the code): dataset generation about US$0.07; S1 live trials about US$0.5; S4/S4b eval runs, judge reproductions (the worker reported an estimate of about US$2, over its US$1.5 cap); S1b tuning runs; the master's recording and eval runs (about US$0.4) and demo rehearsal runs (about US$0.1). These were not centrally summed; the total is well under US$5, so the build is far inside the ~US$50 budget.

Tokens in: workers read almost entirely from cache (cache reads 1.4 M to 27.7 M tokens per task); uncached input per task was 76 to 2,157 tokens. Full figures are in each `reports/<task>.md`.

## Product numbers at the end

- `pnpm check`: green offline in about 25 s (637 pytest, 153 contract + 35 capture + 61 web vitest).
- Replay run: 1–2 s without delay; the demo (`make demo`, 900 ms simulated latency per call) shows the briefing 5.4–5.5 s after the click and passes all 42 capture steps in about 14 s, twice.
- Live run: 15–27 s and US$0.025–0.039 per briefing; the live demo passed in 37.5 s.
- `make eval` live, 3 clients: 34 s; fact recall 73 / 86 / 86 % (82 % avg), citation accuracy 98 % avg, injection resisted on all; four failure scenarios pass.

## What went well

- Strict interfaces written by the master up front (`docs/orchestration/interfaces.md`) let five Gate-1 tasks build in parallel against fakes and integrate with only one trivial conflict (an unused `type: ignore`).
- Worker output quality was high and self-verified: workers merged `main`, ran live trials and reported measured numbers.
- Putting measurement first (G0b) found the Haiku alias does not exist before any design depended on it.

## Top bottlenecks

1. **Contract gap found at the Gate 0 review**: the 8 KB event cap left no way to deliver the final pack. Cost an extra task (G0c, 8 min, US$0.99) and a delayed Gate 1 start. A better plan prompt would specify how the final artefact reaches the client.
2. **Replay recordings are fragile by design**: keys are a hash of the full request, so any prompt/data change invalidates them, and two runs sharing a prefix can overwrite each other's responses with different text (non-deterministic model). Found only at rehearsal (Brightmoor normal replay had an empty "Talking points" section). Fixed by recording the news-outage run through a replay-first/live-fallback wrapper so shared prefixes are identical, plus `agent/tests/test_demo_replay.py` to guard it. The recording helper should be a committed `make record` target.
3. **Eval-driven rework**: the first honest eval (recall 68–82 %) needed a tuning pass (S1b, 16 min) that lifted recall about 8 points. The plan should schedule that loop explicitly instead of discovering it.
4. **Hydration race in the capture demo**: first click after a cold Next dev compile did nothing. Fixed in `packages/capture` (wait for network idle after `goto`).
5. S4 asked whether to wait for S1 instead of continuing; settled with "finish" and a follow-up task. Better: sequence the live-run part as its own task from the start.
6. Orca/CLI friction: `check --wait` replays unacked heartbeats; the `send --type` enum does not include a generic instruction type; sandbox clocks inside workers were coarse so their wall times are understated (the harness numbers above are authoritative).

## Changes for the next plan prompt

- Say who delivers the final artefact to the UI/eval (and require the interface file before tasks start).
- Make "record replay data" a committed command and add an acceptance check that replay output meets quality criteria (all sections populated), not only "no misses".
- Plan for one eval-then-tune iteration after Gate 1, with a cost cap and an anti-overfitting rule (done here and it worked).
- Give each task a hard cap on its own live LLM spend and ask it to read the proxy cost header sums, since one worker overspent its cap.
- Ask the workers to report harness session ids so metrics are not reconstructed.
- State the web production-build requirement for screenshots (the Next dev badge appears in dev mode).
- The user's brief assumed a Haiku alias; verify model aliases in the prompt-writing step.

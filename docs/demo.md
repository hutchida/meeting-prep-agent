# Demo script (about 2 minutes)

The demo runs fully offline in replay mode: recorded model responses from `data/recordings/` are served by the same `LLMClient` interface the live path uses. No API key, no network.

## Before you start

```bash
make setup           # once
make demo            # replay + production web build; same as `make dev` but no Next dev overlay and a watchable timeline
```

`make demo` sets `LLM_MODE=replay` and `REPLAY_DELAY_MS=900` (simulated latency per recorded model call; a run finishes in about 5 s). `make dev` also works (`LLM_MODE=replay make dev`) with the default 250 ms delay.

Presenter URLs:

| URL | What |
| --- | --- |
| http://localhost:3000 | Chat UI |
| http://localhost:8000/health | API health (shows `llm_mode: replay`) |
| http://localhost:3100 | Langfuse traces (optional: `docker compose up -d`, then run with `TRACING=langfuse` and the `LANGFUSE_*` names from `.env.example`) |

## The five steps and what to say

1. **Open http://localhost:3000.** A chat screen with three starter prompts, one per fake client.
   *"This is a meeting-prep agent. I ask in plain language; behind it are four sub-agents, a writer and a verifier, all hand-written, no agent framework."*
2. **Click "Prep me for my meeting with Brightmoor on Thursday".** The step timeline shows the plan, then four sub-agents (Correspondence, Documents, News, Attendees) running in parallel, each with its tool calls and the ids it found.
   *"The orchestrator resolves the client and the meeting from the calendar, relative to a fixed demo date, then fans out. Each agent has its own loop and read-only tools; there is no send, write or delete tool at all."*
3. **Within about 5 seconds the briefing renders:** seven sections, every sentence cited.
   *"Writer drafts, then a cite-or-drop verifier checks every citation exists and supports the sentence. Unsupported sentences are removed and counted. The stats row shows steps, tokens and cost of the recorded live run."*
4. **Click a citation chip.** A side panel opens with the underlying email, document, chat, news item or calendar event.
   *"Every fact traces back to a source item. Email text is treated as untrusted data; one email in the dataset is a prompt-injection attempt and the agent never acts on it."*
5. **Tick "Simulate news outage" and run the same prompt again.** The timeline shows the News agent retry once and then fail; Recent news says it could not be reached; the other six sections still render, under a "Partial briefing" banner.
   *"Failures are expected: tool calls retry once with backoff, a failed sub-agent does not stop the run, and the briefing names what is missing."*

## Closing line

*"The same code runs against a LiteLLM proxy live, and the data sits behind an interface so a Microsoft Graph source drops in later. Evals, guardrails and the loop are in the README."*

## Automated rehearsal

`packages/capture` runs steps 1 to 5 in a headless browser, asserts them and writes screenshots and a GIF:

```bash
pnpm --filter @mpa/capture run install-browsers   # once
make demo                                         # in one terminal
pnpm --filter @mpa/capture run capture -- demo    # replay: must finish in < 60 s, briefing within 10 s of the click
pnpm --filter @mpa/capture run capture -- demo --live --out docs/media/live   # against the live model (needs LITELLM_* set)
```

Last rehearsal (2026-11-17, after the re-recording): replay twice, 14.3 s and 13.8 s for all 42 steps, briefing visible 5.6 s and 5.4 s after the click; live once, 47.5 s total, briefing after 22.7 s. Media: [docs/media/demo.gif](media/demo.gif), [docs/media/live/demo.gif](media/live/demo.gif).

## If something goes wrong

- Blank timeline or error toast: check http://localhost:8000/health returns `ok`.
- A replay miss means a prompt or the data changed after recording. `agent/tests/test_demo_replay.py` guards this in CI; re-record with `make record` (see README).
- Outage run still shows news: confirm the toggle is ticked before pressing Send.

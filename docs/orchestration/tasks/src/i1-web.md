# Task i1-web — Gate 2: Chat UI (Next.js App Router + Tailwind)

Target wall time: about 60 minutes. No demo replays and no screenshot tooling in this task: do not record demo runs, do not write Playwright scripts, do not touch `packages/capture` (another task owns it; you only implement the test ids it expects). Do not call the live LLM.

## Goal
A chat UI like Copilot in Teams on `http://localhost:3000` that talks to the API on `http://localhost:8000`: message box, three starter prompts, a live step timeline fed by SSE (plan, four parallel sub-agents, tool calls, retries, failures), the briefing rendered as markdown with clickable citations opening a source side panel, a "Simulate news outage" toggle, and run stats (steps, tokens, cost, time).

## Owned files
- `apps/web/**`
- `docs/orchestration/reports/i1-web.md`

Must NOT touch: `packages/**` (contract is read-only: import types/schemas from `@mpa/contract`; **no new fields, no new event types, no contract changes**, if something is missing, stop and report), `agent/**`, `data/**`, `docs/**` except your report, `README.md`, `DECISIONS.md`, `Makefile`, root config. Dependencies: add to `apps/web/package.json` only (keep them few: a markdown renderer such as `react-markdown` is fine; no UI kit required).

## Inputs (already on main)
- API (merged): `POST http://localhost:8000/briefings` (body `BriefingRequest` = `{message, fail_source?}`) streams SSE; each message is `event: <AgentEvent.type>` + `data: <AgentEvent JSON>`; stream ends after `run_done`. `GET /sources/{type}/{id}` returns a `SourceItem`. `GET /health`. CORS allows `http://localhost:3000`.
- Contract types and zod schemas in `@mpa/contract` (`AgentEvent`, `BriefingPack`, `BriefingRequest`, `SourceItem`, citation helpers `parseCitations`/`citationToken`); fixtures in `packages/contract/fixtures/` (valid AgentEvent and BriefingPack examples for every variant: use them for unit tests and Storybook-less development).
- `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`) is the only config; no secrets in the browser.

## UX requirements
1. **Landing/chat screen:** header ("Meeting Prep Agent"), empty state with **three starter prompt buttons**, exactly: "Prep me for my meeting with Halden Pay on Wednesday", "Prep me for my meeting with Brightmoor on Thursday", "Prep me for my meeting with Kettle & Crumb on Friday". Message box + send button; Enter to send; disabled while a run is active (with a visible stop button that aborts the fetch).
2. **Teams-Copilot feel:** user bubble right, assistant card left, calm neutral palette, readable type, good spacing, responsive down to ~900 px wide, keyboard accessible, visible focus rings, `aria-live` for streaming updates. Tasteful, not flashy; no emoji spam.
3. **Live step timeline** (inside the assistant card, above the briefing; collapsible once done): rows appear as SSE events arrive: plan (show the plan text), four sub-agents shown as parallel lanes/columns or a grouped list with per-agent status (running / retrying / failed / done) and their tool calls streaming under each (tool name + short args + result summary: item count and ids), retries (attempt, backoff, error summary) in amber, failures (`subagent_failed`) in red with the reason, budget hit notice, verifier result ("kept X of Y sentences, dropped Z"). Timeline row elements carry `data-testid="timeline-event"` with `data-type` (the AgentEvent type) and `data-agent` when the event has an agent. The container is `data-testid="step-timeline"`.
4. **Briefing:** when the `draft` event arrives show a skeleton/preview; when the final pack is available (`draft` after verification or the pack in `run_done`, whichever the contract defines; follow the contract exactly) render the 7 sections in order with titles. Container `data-testid="briefing"`; each section `data-testid="section-<id>"` with ids `meeting_at_a_glance, client_snapshot, recent_news, where_we_left_off, open_items, attendees, talking_points_and_risks`. Sentences render as markdown text; **citations** (structured `citations[]` and/or inline tokens like `[email:E123]`) render as small chips/superscripts, `data-testid="citation"` with `data-cite="email:E123"`. Empty sections show their note plainly. Partial packs show a clear "Partial briefing" banner listing `gaps` (source + reason).
5. **Source side panel:** clicking a citation opens a right-side panel (`data-testid="source-panel"`, close button `source-panel-close`, Esc closes) that fetches `GET /sources/{type}/{id}` and renders the item by type (email: from/to/date/subject/body; chat; doc with title/kind/body; news with source/date/url as plain text; contact; calendar event). Loading and error states. Treat all text as untrusted: render as text/markdown with no raw HTML, never `dangerouslySetInnerHTML`; links from data are not auto-opened.
6. **"Simulate news outage" toggle:** `data-testid="toggle-news-outage"`, sends `fail_source: "news"` in the request body. Place it near the message box with a short helper text.
7. **Run stats:** `data-testid="run-stats"` showing steps, tokens in/out, cost (USD, 4 decimals), elapsed time (live ticking while running; final from `run_done`/pack stats).
8. Other ids required (interface with the capture task, do not rename): chat input `chat-input`, send button `chat-send`, starters `starter-halden`, `starter-brightmoor`, `starter-kettle`.
9. Errors: API unreachable → friendly inline error with retry; a stream that ends without `run_done` → "The run ended unexpectedly" state; malformed events are skipped safely (validate with the contract zod schema; show an unobtrusive notice).

## Engineering
- Next.js App Router, Tailwind v4, TypeScript strict. Keep components small: SSE reader (fetch + ReadableStream parser; EventSource can't POST) as a hook with unit tests, an event reducer (pure function: events → timeline/agents/briefing state) with thorough tests driven by contract fixtures, citation rendering, source panel, stats.
- The reducer must handle interleaved events from parallel agents and out-of-order arrival safely (ordering by `seq` within a run).
- vitest tests (offline, in `pnpm check`): reducer, SSE parser (chunk boundaries splitting frames/UTF-8, keep-alive comments), citation tokenisation, rendering tests of the briefing and timeline components (use `@testing-library/react` + `jsdom` if added), source panel states. `pnpm --filter @mpa/web build` must succeed.
- Perf: first paint fast, no layout jumps while streaming.

## Acceptance
- `pnpm check` green (offline), `pnpm --filter @mpa/web build` succeeds.
- `make dev` with `LLM_MODE=replay` serves the UI; you may run the dev servers and click through manually with the ids above, but do NOT record or commit recordings/screenshots/GIFs. If recordings are not yet in `data/recordings/`, drive the UI with a small mock SSE server of your own under `apps/web/tests/` (fixtures from the contract) for manual checks.
- Merge report committed.

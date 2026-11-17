# Run events (AgentEvent stream)

Every run emits `AgentEvent`s (each <= 8 KB, `seq` strictly increasing from 0, one `run_id`). A whole `BriefingPack` (up to 40 KB) cannot travel in one event, so the finished pack is **rebuilt from the stream** with `assemblePack` / `assemble_pack`. Decision D9.

## Order

`run_started`, `plan`, then per sub-agent `subagent_started` -> (`tool_call` -> `tool_result` | `retry`)* -> `subagent_done` | `subagent_failed` (the four agents interleave; `budget_hit` appears at most once, anywhere), then `verifier_result`, then **exactly 7 `draft` events** (one section each, canonical order, only the last has `complete=true`), then `run_done` (always last, even on failure). Only verified sentences are ever emitted in `draft`s.

Sections: `meeting_at_a_glance`, `client_snapshot`, `recent_news`, `where_we_left_off`, `open_items`, `attendees`, `talking_points_and_risks`.

## Events

| Event | Meaning | Render in a UI? |
|---|---|---|
| `run_started` | run begins; `model` used | header |
| `plan` | `client`, `meeting_id`, `meeting_title`, `meeting_start`, one task per agent | timeline (agent lanes) |
| `subagent_started` / `_done` / `_failed` | agent lifecycle; `_done` carries `findings_count` and `gaps`, `_failed` a `reason` | timeline status per agent |
| `tool_call` / `tool_result` | one tool call and its outcome (`ok`, `item_count`, `ids`, `summary`) | timeline detail |
| `retry` | transient failure, backing off | timeline (warning) |
| `budget_hit` | steps / tokens / cost / time budget reached | banner |
| `verifier_result` | sentence counts kept / dropped and why | verifier chip |
| `draft` | one verified section (`complete=true` on the 7th) | **briefing sections, appended as they arrive** |
| `run_done` | `partial` flag and run `stats` | footer, stop spinner |

The briefing text shown to a user comes only from `draft` events (or the assembled pack), never from anything else.

## Assembling the pack

```ts
import { assemblePack, checkEventOrder, PackAssemblyError } from "@mpa/contract";
const pack = assemblePack(events); // BriefingPack
```

```python
from mpa.contract import assemble_pack, check_event_order, PackAssemblyError
pack = assemble_pack(events)  # BriefingPack (accepts AgentEvent models or dicts)
```

Behaviour (identical in both languages, shared cases in `fixtures/runs/assemble_cases.json`):

- Events are sorted by `seq`; duplicate `seq` or mixed `run_id`s raise `PackAssemblyError`.
- `run_id`, `model` <- `run_started`; `client`, `meeting` <- `plan`; `sections` <- the `draft`s by section id; `verifier` <- `verifier_result` (derived from the sentences if missing); `stats` <- `run_done` (derived if missing).
- `gaps` come, in `seq` order and de-duplicated (max 12), from `subagent_failed` (agent mapped to its source: correspondence=email, documents=docs, news=news, attendees=contacts), the `gaps` of `subagent_done`, and `budget_hit` (one `budget` gap per agent that never finished).
- `partial` is true when there is any gap, a `budget_hit`, `run_done.partial`, or no `run_done`.
- No `run_done` and no complete draft (a cut-off stream): missing sections become empty sections and unfinished agents become `error` gaps. A finished run with sections missing raises `PackAssemblyError`.
- The result is validated against `BriefingPack` and the 40 KB limit.

`checkEventOrder` / `check_event_order` return the list of order violations (empty when the stream is well formed); use it in tests, not at runtime.

Example streams and the packs they must assemble to: `fixtures/runs/run.brightmoor.normal`, `run.brightmoor.news_down`, `run.halden.budget_hit` (`*.events.json`, `*.pack.json`).

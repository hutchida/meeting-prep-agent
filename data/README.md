# Fake dataset

A small, fully fictional data set for the meeting prep agent: a consultancy (**Northwind Advisory**) and
three clients, plus a few hundred unrelated real emails as noise. Everything is committed so the repo
runs offline.

## Layout

One JSON object per line, UTF-8, compact JSON with sorted keys and `\n` line endings. Each line validates
against the schema in `packages/contract/schema/` (`Email`, `ChatMessage`, `Doc`, `CalendarEvent`,
`Contact`, `NewsItem`).

| File | Contents | Schema |
|---|---|---|
| `emails.jsonl` | 67 synthetic emails + 350 Enron noise emails | `Email` |
| `chats.jsonl` | 28 chat messages (one shared channel per client) | `ChatMessage` |
| `docs.jsonl` | 21 documents (proposals, SOWs, notes) | `Doc` |
| `calendar.jsonl` | 3 meetings in the demo week + 6 earlier meetings | `CalendarEvent` |
| `contacts.jsonl` | 13 people (4 Northwind staff, 9 client contacts) | `Contact` |
| `news.jsonl` | 26 fictional news items | `NewsItem` |
| `PLOT.md` | Ground truth for evals. **The agent must never read it.** | |
| `_gen_cache/` | Committed LLM response cache so generation is reproducible offline | |
| `recordings/` | Empty; replay data is recorded later by other tasks | |
| `raw/` | Gitignored raw downloads (the Enron corpus); never committed | |

## IDs and citations

`E<n>` email, `C<n>` chat, `D<n>` doc, `N<n>` news, `P<n>` contact, `M<n>` calendar event. Numbers are
contiguous per file, ordered by date (synthetic emails first, then the Enron sample). In text they are
cited as `[email:E123]`, `[chat:C9]`, `[doc:D7]`, `[news:N4]`, `[contact:P2]`, `[cal:M1]`.

## The story

`DEMO_NOW` is `2026-03-09T09:00:00Z` (a Monday). The user is Sam Reyes (`P1`).

| Client | Sector | Meeting | When |
|---|---|---|---|
| Halden Pay | fintech | `M1` onboarding redesign checkpoint | Wed 2026-03-11 |
| Brightmoor Renewables | wind and solar | `M2` PPA board pre-read (the demo meeting) | Thu 2026-03-12 |
| Kettle & Crumb | consumer snacks | `M3` Q2 retail plan | Fri 2026-03-13 |

Each client has 30-34 emails and chats over the three months before `DEMO_NOW`, 7 docs, and 8-9 news items,
including look-alike companies that must not be attributed to the client (for example "Brightmoor Capital
Partners"). Each client has exactly one planted contradiction, one promise that was not kept and one explicit
deadline. Halden Pay also has one prompt-injection email. All of it is listed, with source ids, in `PLOT.md`.

Everything fictional uses the reserved `example.test` domain space.

## Regenerating

```sh
make data                                  # or: cd agent && uv run python scripts/generate_data.py
cd agent && uv run python scripts/generate_data.py --offline     # cache only: no network, no key
```

- Structure (people, ids, dates, plot facts) is deterministic from a fixed seed in `agent/scripts/_gen_plot.py`.
- Prose comes from the LiteLLM proxy (`LITELLM_BASE_URL`, `LITELLM_API_KEY`, `LLM_MODEL` from `.env`) at
  `temperature=0` with a fixed seed. Every response is cached by request hash in
  `_gen_cache/llm_cache.jsonl`, so `--offline` reproduces all files byte for byte (a pytest checks this).
  The cache stores prompts' hashes and responses only, never URLs, headers or keys. Changing a prompt or
  brief changes the hash and needs network access to fill the cache again.
- Enron items are re-sampled from `data/raw/maildir` if it exists, otherwise the committed Enron lines in
  `emails.jsonl` are reused (`--no-raw` forces that). To re-download: fetch the CMU corpus (release dated
  2015-05-07), extract it to `data/raw/`, then run `agent/scripts/sample_enron.py` to preview the sample.

## Enron noise: attribution and licence

350 emails are a seeded random sample of **the Enron Email Dataset** (CALO Project; William W. Cohen, MLD,
Carnegie Mellon University; public release, version dated 2015-05-07). They are unrelated to the fictional
clients and exist only as retrieval noise. Processing: plain-text body only (attachments dropped), bodies
truncated so each email is at most 6 KB, phone numbers and runs of six or more digits replaced by
`[redacted]`. Original dates (1999-2002), senders and recipients are kept, so these are the only items outside
the three-month window and the only ones with non-`.test` addresses. They carry `origin: "enron"`.
The raw download was fetched successfully (443 MB, about 12 minutes), so the noise is real data, not
synthetic substitutes.

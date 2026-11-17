# Measurements (Gate 0b)

Measured once on 2026-11-17 (UTC) from a developer laptop. Each number is a single observation, so
treat latencies as ±0.5 s. Prices are not list prices: they are the USD cost the proxy reported
per call (`x-litellm-response-cost`), and the per-million-token rates below are derived from two
calls of different sizes per model. Nothing here contains the proxy address or any key.

## 1. LiteLLM proxy

`GET /models` returns 19 ids:
`azure/gpt-5`, `azure/gpt-5-mini`, `azure/gpt-5.5`, `azure/gpt-5.6-terra`, `azure/text-embedding-3-small`,
`fergus-om`, `vertex-ai-claude-opus-4.7`, `vertex-ai-claude-opus-4.8`, `vertex-ai-claude-sonnet-4.5`,
`vertex-ai-claude-sonnet-4.6`, `vertex-ai-claude-sonnet-4@20250514`, `vertex-ai-claude-sonnet-5`,
`vertex-ai-gemini-2.0-flash`, `vertex-ai-gemini-2.5-pro`, `vertex-ai-gemini-2.5-pro-exp-03-25`,
`vertex-ai-gemini-3-flash-preview`, `vertex-ai-gemini-3.1-pro-preview`,
`vertex-ai-gemini-3.1-pro-preview-customtools`, `vertex-ai-gemini-3.6-flash`.

**No Haiku alias is listed** (confirms DECISIONS.md D2).

### One forced tool call per candidate

Request: one `get_weather(city)` tool, `tool_choice` forced to that function, prompt "What is the
weather in Paris? Use the tool." ("short"), and the same question after ~2.4k tokens of filler ("long").
Every call that succeeded returned a valid tool call with `{"city": "Paris"}`.

| Model | Tool call works | Short: latency / tokens in+out / cost | Long (~2.4k): latency / tokens in+out / cost | Derived rate (in / out per 1M tokens) |
|---|---|---|---|---|
| `vertex-ai-gemini-3-flash-preview` | Y | 1.6-1.8 s / 31+73-88 / $0.00023-0.00028 | 1.4-1.5 s / 2379+86-119 / $0.00145-0.00155 | $0.50 / $3.00 |
| `vertex-ai-gemini-3.6-flash` | Y | 1.6 s / 31+80-83 / $0.00032-0.00033 | 1.5 s / 2379+87-97 / $0.00211-0.00215 | $0.75 / $3.75 |
| `azure/gpt-5-mini` | Y (no `temperature`) | 3.2 s / 133+87 / $0.00021 | 2.7 s / 2480+87 / $0.00079 | $0.25 / $2.00 |
| `vertex-ai-claude-sonnet-4.6` | Y | 1.1 s / 663+33 / $0.00248 | 1.0 s / 3141+33 / $0.00992 | $3.00 / $15.00 |
| `vertex-ai-claude-sonnet-5` | Y (no `temperature`) | 1.6 s / 569+34 / $0.00163 | 1.4 s / 4999+34 / $0.01137 | $2.20 / $11.00 |
| `vertex-ai-claude-opus-4.8` | Y (no `temperature`) | 1.3 s / 505+34 / $0.00371 | 1.0 s / 4935+34 / $0.02808 | $5.50 / $27.50 |
| `azure/gpt-5.5` | Y (no `temperature`) | 2.0 s / 51+18 / $0.00080 | 2.4 s / 2398+18 / $0.01253 | $5.00 / $30.00 |
| `azure/gpt-5.6-terra` | Y (no `temperature`) | 3.0 s / 51+18 / $0.00032 | 1.6 s / 2398+18 / $0.00615 | ~$2.50 / ~$10.60 |

Findings that affect the `LLMClient`:

- **`temperature=0` is rejected (HTTP 400, `UnsupportedParamsError`) by `azure/gpt-5-mini`, `azure/gpt-5.5`,
  `azure/gpt-5.6-terra`, `vertex-ai-claude-sonnet-5` and `vertex-ai-claude-opus-4.8`.** The Gemini models and
  `vertex-ai-claude-sonnet-4.6` accept it. The client should omit `temperature` (or retry once without it) for
  the first group.
- **Gemini 3 "thinking" tokens count against `max_tokens`.** With `max_tokens=60` the Flash model returned
  empty content and no tool call. Use a generous limit (the data generator uses 3000).
- `seed` is accepted by the Gemini model, but two identical `temperature=0, seed=7` calls did not produce
  identical text, so reproducibility must come from caching, not the provider.
- The proxy exposes cost per call in the `x-litellm-response-cost` response header, so the agent can account
  for cost without a price table. Claude calls carry about 500-630 extra prompt tokens for tool-use overhead.

### Rate limits and concurrency

| Check | Result |
|---|---|
| `x-ratelimit-*` response headers | none returned (on `/models` or on `/chat/completions`) |
| 6 concurrent plain calls to `vertex-ai-gemini-3-flash-preview` | 6/6 HTTP 200, latency 1.2-2.5 s, no 429 |
| 6 concurrent forced tool calls to the same model | 6/6 HTTP 200 with a tool call, latency 1.1-3.5 s, no 429 |

### Budget check

The sample briefing stats in the contract fixtures use 21,840 prompt and 3,120 completion tokens across 14 steps.
At the derived rates that is about:

| Model | Cost per briefing | Within US$0.05? |
|---|---|---|
| `vertex-ai-gemini-3-flash-preview` | $0.020 | yes |
| `vertex-ai-gemini-3.6-flash` | $0.028 | yes |
| `azure/gpt-5-mini` | $0.012 | yes, but 2.7-3.2 s per call and `temperature` quirks |
| `vertex-ai-claude-sonnet-5` | $0.082 | no |
| `vertex-ai-claude-sonnet-4.6` | $0.112 | no |
| `azure/gpt-5.6-terra` | $0.087 | no |
| `azure/gpt-5.5` | $0.20 | no |
| `vertex-ai-claude-opus-4.8` | $0.21 | no |

With about 1.5 s per call and four sub-agents running in parallel, 14 sequential-equivalent steps stay far
below the 60 s target (roughly 20-30 s).

## 2. Enron corpus (CMU release, 2015-05-07)

| Step | Result |
|---|---|
| Download | HTTP 200, 443,254,787 bytes (423 MiB), 743 s (12.4 min), about 0.6 MB/s. Under the 15 min cut-off. |
| Extraction (`tar -xzf`) | 86 s; 2.5 GB on disk, 517,401 files under `maildir/` |
| Where it lives | `data/raw/` (gitignored; `git check-ignore data/raw/x` confirms) |
| Sampling | see `agent/scripts/sample_enron.py` (seeded; the sample is the only part committed) |

The download worked, so the Enron noise is real CMU data, not synthetic.

## 3. Recommendation

- **Default `LLM_MODEL=vertex-ai-gemini-3-flash-preview`.** It is the cheapest candidate that does reliable
  tool calling at about 1.5 s per call (6/6 forced tool calls under concurrency), costing about $0.02 per
  briefing at the fixture token volume (target: below $0.05 and below 60 s). It accepts `temperature=0`.
- **Fallback: `vertex-ai-gemini-3.6-flash`.** Same latency and tool behaviour, about 40% dearer ($0.028 per
  briefing). If quality matters more than cost for a one-off run, `vertex-ai-claude-sonnet-4.6` works but costs
  about $0.11 per briefing, over budget.
- `azure/gpt-5-mini` is cheaper per token but twice as slow per call, so it is not recommended as the default.
- Caveat: reliability was judged from 8 forced single-call checks plus 6 concurrent ones, not from a long
  multi-turn run. The G-gate that builds the loop should re-check tool-call reliability with real prompts.

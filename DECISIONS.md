# Decisions

Each entry: decision, why, alternatives considered. Newest at the bottom.

## D1. Repo location is the Orca-registered folder
- **Decision:** Use `/Users/hutchida/orca/projects/meeting-prep-agent` (already a git repo registered in Orca) instead of `~/GIT/meeting-prep-agent`.
- **Why:** Orca worktree/agent orchestration needs a registered repo; it is already a fresh local git repo with no remote.
- **Alternatives:** Create `~/GIT/meeting-prep-agent` and register it with `orca repo add` (extra moving part, no benefit).

## D2. LLM model: no Claude Haiku alias exists on the proxy
- **Decision:** `LLM_MODEL` has no Haiku default. The proxy `/models` lists no Haiku alias (Claude entries are Sonnet 4/4.5/4.6/5 and Opus 4.7/4.8 on Vertex). The default is the cheapest tool-calling model that passes measurement in G0b, with `vertex-ai-gemini-3-flash-preview` as the pre-measured candidate (tool calling works, ~1.4 s for a tiny call). Configurable through `LLM_MODEL`.
- **Why:** The $0.05/briefing and 60 s targets are not realistic with Sonnet-class pricing across four sub-agents; a Flash-class model is the nearest in price/latency to Haiku.
- **Alternatives:** `vertex-ai-claude-sonnet-4.6` (works, costs several times more); ask the user (not blocking). Swap by changing one env var.

## D3. Credentials handled locally, never committed
- **Decision:** `LITELLM_BASE_URL` / `LITELLM_API_KEY` were not present in the orchestrator's shell. They were supplied in the build prompt. They are kept only in a gitignored `.env` (mode 600) in the repo root and copied into each task worktree's gitignored `.env`; they never appear in task prompts, reports, recordings, traces or commits.
- **Why:** Workers launched by Orca do not inherit the user's interactive shell environment.
- **Alternatives:** Put them in `~/.zshrc` (changes the user's shell config, not requested).

## D4. Worker agent and model
- **Decision:** Workers run as the `opencode` agent with `github-copilot/claude-sonnet-5.5` (test call confirmed OK). Token/cost metrics may be "unavailable" if the harness does not expose them.
- **Why:** Same signed-in account as the orchestrator; strong coding model.
- **Alternatives:** `claude` CLI agent (not tested for account/billing).

## D5. Python type checker is mypy; web lint uses plain typescript-eslint
- **Decision:** `mypy --strict` for agent/, flat-config ESLint with typescript-eslint for TS.
- **Why:** Simple, offline, no node download (pyright's pip wrapper fetches node).
- **Alternatives:** pyright; eslint-config-next.

## D6. Pydantic models for the contract live in agent/src/mpa/contract/ and are owned by the contract task
- **Decision:** G0b owns `agent/src/mpa/contract/**` (Pydantic models mirroring the JSON Schema) plus `agent/tests/test_contract*.py`.
- **Why:** The contract has a single owner; service tasks import, never redefine, models.
- **Alternatives:** Each service task writes its own models (drift risk).

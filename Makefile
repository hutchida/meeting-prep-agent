.PHONY: setup dev dev-api dev-web dev-web-prod demo record test eval data check

setup:
	pnpm install
	cd agent && uv sync

dev:
	@$(MAKE) -j2 dev-api dev-web

dev-api:
	cd agent && uv run uvicorn mpa.api.app:app --host 127.0.0.1 --port 8000 --reload

dev-web:
	pnpm --filter @mpa/web dev

# Rehearsal/demo: offline replay, production web build (no Next dev overlay), watchable timeline
demo:
	pnpm --filter @mpa/web build
	@LLM_MODE=replay REPLAY_DELAY_MS=$${REPLAY_DELAY_MS:-900} $(MAKE) -j2 dev-api dev-web-prod

dev-web-prod:
	pnpm --filter @mpa/web start

test check:
	pnpm check

# Re-record the demo replay set live (needs LITELLM_* in .env; replaces data/recordings/ only if every scenario passes the quality gate)
record:
	cd agent && uv run python scripts/record_demo.py

eval:
	cd agent && uv run python -m mpa.evals

data:
	cd agent && uv run python scripts/generate_data.py

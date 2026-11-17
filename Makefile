.PHONY: setup dev dev-api dev-web test eval data check

setup:
	pnpm install
	cd agent && uv sync

dev:
	@$(MAKE) -j2 dev-api dev-web

dev-api:
	cd agent && uv run uvicorn mpa.api.app:app --host 127.0.0.1 --port 8000 --reload

dev-web:
	pnpm --filter @mpa/web dev

test check:
	pnpm check

eval:
	cd agent && uv run python -m mpa.evals

data:
	cd agent && uv run python scripts/generate_data.py

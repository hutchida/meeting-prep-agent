"""Fallback price table (USD per 1M tokens, input/output) used when the proxy sends no cost header.

Values are the rates derived from the proxy's reported per-call cost in
docs/orchestration/measurements.md (section 1), keyed by model alias.
"""

from __future__ import annotations

import logging

from mpa.contract import Usage

log = logging.getLogger(__name__)

PRICES_PER_MILLION: dict[str, tuple[float, float]] = {
    "vertex-ai-gemini-3-flash-preview": (0.50, 3.00),
    "vertex-ai-gemini-3.6-flash": (0.75, 3.75),
    "azure/gpt-5-mini": (0.25, 2.00),
    "vertex-ai-claude-sonnet-4.6": (3.00, 15.00),
    "vertex-ai-claude-sonnet-5": (2.20, 11.00),
    "vertex-ai-claude-opus-4.8": (5.50, 27.50),
    "azure/gpt-5.5": (5.00, 30.00),
    "azure/gpt-5.6-terra": (2.50, 10.60),
}

_warned: set[str] = set()


def estimate_cost(model: str, usage: Usage) -> float:
    """Cost in USD for `usage`; unknown models cost 0.0 and warn once per model."""
    price = PRICES_PER_MILLION.get(model)
    if price is None:
        if model not in _warned:
            _warned.add(model)
            log.warning("no price known for model %r; cost is reported as 0.0", model)
        return 0.0
    return (usage.prompt_tokens * price[0] + usage.completion_tokens * price[1]) / 1_000_000

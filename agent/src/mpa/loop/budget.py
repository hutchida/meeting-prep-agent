"""Per-run budgets: steps per agent, tokens and cost for the whole run."""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable
from typing import Any, Literal

from mpa.contract import Usage

BudgetKind = Literal["steps", "tokens", "cost", "time"]


class BudgetExceeded(Exception):
    def __init__(self, kind: BudgetKind, limit: float, used: float) -> None:
        super().__init__(f"{kind} budget of {limit:g} reached (used {used:g})")
        self.kind = kind
        self.limit = limit
        self.used = used


class Budget:
    """Thread- and task-safe; `begin_step` is the check made before every LLM call."""

    def __init__(self, max_steps_per_agent: int, max_tokens: int, max_cost_usd: float) -> None:
        self.max_steps_per_agent = max_steps_per_agent
        self.max_tokens = max_tokens
        self.max_cost_usd = max_cost_usd
        self._lock = threading.Lock()
        self._steps: defaultdict[str, int] = defaultdict(int)
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost_usd = 0.0
        self._reported = False

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    @property
    def total_steps(self) -> int:
        with self._lock:
            return sum(self._steps.values())

    def steps_for(self, agent: str) -> int:
        with self._lock:
            return self._steps[agent]

    def exhausted(self) -> BudgetExceeded | None:
        """The run-wide limit that is already reached, if any (steps are per agent)."""
        with self._lock:
            return self._global_hit()

    def _global_hit(self) -> BudgetExceeded | None:
        if self.tokens_in + self.tokens_out >= self.max_tokens:
            return BudgetExceeded("tokens", self.max_tokens, self.tokens_in + self.tokens_out)
        if self.cost_usd >= self.max_cost_usd:
            return BudgetExceeded("cost", self.max_cost_usd, round(self.cost_usd, 6))
        return None

    def begin_step(self, agent: str) -> int:
        """Reserve the next LLM call for `agent`; raises BudgetExceeded instead of exceeding."""
        with self._lock:
            if (hit := self._global_hit()) is not None:
                raise hit
            if self._steps[agent] >= self.max_steps_per_agent:
                raise BudgetExceeded("steps", self.max_steps_per_agent, self._steps[agent])
            self._steps[agent] += 1
            return self._steps[agent]

    def charge(self, usage: Usage) -> None:
        with self._lock:
            self.tokens_in += usage.prompt_tokens
            self.tokens_out += usage.completion_tokens
            self.cost_usd += usage.cost_usd

    def claim_report(self) -> bool:
        """True exactly once: whoever gets it emits the single `budget_hit` event."""
        with self._lock:
            first = not self._reported
            self._reported = True
            return first

    @property
    def hit_reported(self) -> bool:
        return self._reported


Emit = Callable[..., Any]


def report_budget_hit(budget: Budget, hit: BudgetExceeded, emit: Emit) -> None:
    if budget.claim_report():
        emit("budget_hit", budget=hit.kind, limit=hit.limit, used=hit.used)

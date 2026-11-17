from __future__ import annotations

import threading

import pytest

from mpa.contract import Usage
from mpa.loop import Budget, BudgetExceeded, report_budget_hit


def test_step_limit_is_per_agent() -> None:
    b = Budget(2, 10_000, 1.0)
    assert [b.begin_step("a"), b.begin_step("a"), b.begin_step("b")] == [1, 2, 1]
    with pytest.raises(BudgetExceeded) as exc:
        b.begin_step("a")
    assert exc.value.kind == "steps" and exc.value.limit == 2
    assert b.total_steps == 3


def test_token_and_cost_limits_apply_to_the_whole_run() -> None:
    b = Budget(8, 1000, 0.05)
    b.charge(Usage(prompt_tokens=600, completion_tokens=400, cost_usd=0.01))
    with pytest.raises(BudgetExceeded) as exc:
        b.begin_step("x")
    assert exc.value.kind == "tokens" and exc.value.used == 1000
    c = Budget(8, 10**9, 0.05)
    c.charge(Usage(cost_usd=0.05))
    with pytest.raises(BudgetExceeded) as exc2:
        c.begin_step("y")
    assert exc2.value.kind == "cost"
    assert c.exhausted() is not None


def test_hit_is_reported_exactly_once() -> None:
    b = Budget(1, 10, 1.0)
    events: list[tuple[str, dict[str, object]]] = []
    hit = BudgetExceeded("tokens", 10, 12)
    for _ in range(3):
        report_budget_hit(b, hit, lambda t, **f: events.append((t, f)))
    assert events == [("budget_hit", {"budget": "tokens", "limit": 10, "used": 12})]


def test_thread_safe_accounting() -> None:
    b = Budget(10_000, 10**9, 10**6)

    def work() -> None:
        for _ in range(500):
            b.begin_step("a")
            b.charge(Usage(prompt_tokens=2, completion_tokens=1, cost_usd=0.001))

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert b.steps_for("a") == 4000 and b.tokens_in == 8000 and b.tokens_out == 4000
    assert b.cost_usd == pytest.approx(4.0)

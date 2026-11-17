from __future__ import annotations

import pytest

from mpa.contract import DataSourceError
from mpa.guardrails.faults import FaultInjectingDataSource, InjectedFault
from test_agents_fakes import FakeData

CASES = {
    "news": {"search_news", "get_news"},
    "email": {"search_email", "get_email", "search_chat", "get_chat"},
    "docs": {"search_docs", "get_doc"},
    "all": {
        "search_email", "get_email", "search_chat", "get_chat", "search_docs", "get_doc",
        "search_news", "get_news", "get_calendar", "get_contact", "find_contacts",
    },
}  # fmt: skip
ARGS = {
    "search_email": ("x",), "search_chat": ("x",), "search_docs": ("x",), "search_news": ("x",),
    "find_contacts": ("x",), "get_email": ("E1",), "get_chat": ("C1",), "get_doc": ("D1",),
    "get_news": ("N1",), "get_contact": ("P1",), "get_calendar": (),
}  # fmt: skip


@pytest.mark.parametrize("fail", list(CASES))
async def test_only_the_named_sources_fail(fail: str) -> None:
    ds = FaultInjectingDataSource(FakeData(), fail)  # type: ignore[arg-type]
    for method, args in ARGS.items():
        call = getattr(ds, method)
        if method in CASES[fail]:
            with pytest.raises(DataSourceError) as exc:
                await call(*args)
            assert isinstance(exc.value, InjectedFault) and "injected fault" in str(exc.value)
        else:
            await call(*args)


async def test_no_fault_passes_through_and_source_item_lookup_is_typed() -> None:
    ds = FaultInjectingDataSource(FakeData(), None)
    assert (await ds.get_email("E1")).id == "E1"
    news_down = FaultInjectingDataSource(FakeData(), "news")
    with pytest.raises(InjectedFault):
        await news_down.get_source("news", "N1")
    assert (await news_down.get_source("email", "E1")).root.id == "E1"

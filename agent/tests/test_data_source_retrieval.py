"""Retrieval quality over the committed dataset, using ground truth from data/PLOT.md."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from mpa.contract import SearchHit
from mpa.data import FakeDataSource

DATA = Path(__file__).resolve().parents[2] / "data"
Search = Callable[..., Awaitable[list[SearchHit]]]


@pytest.fixture(scope="module")
def ds() -> FakeDataSource:
    return FakeDataSource(DATA)


def _is_enron(id_: str) -> bool:
    return id_.startswith("E") and int(id_[1:]) > 67


# (client, kind, natural-language query, expected ids that must all be in the top 5)
CASES: list[tuple[str, str, str, list[str]]] = [
    ("halden", "email", "Halden Pay compliance deadline safeguarding attestation", ["E49"]),
    ("halden", "email", "Halden Pay go-live date for the onboarding flow", ["E47"]),
    ("halden", "chat", "Kofi says engineering will ship on 28 April", ["C22"]),
    ("halden", "docs", "Halden Pay SOW fixed fee and instalments", ["D4"]),
    ("halden", "email", "which KYC vendor did they choose, VeriTrace or IdentiQ", ["E37"]),
    ("halden", "email", "KYC risk-scoring matrix Ingrid promised by 27 February", ["E46"]),
    ("halden", "chat", "risk scoring matrix Ingrid audit prep", ["C25", "C28"]),
    ("halden", "docs", "chargeback rate in Q4", ["D9"]),
    ("halden", "docs", "steering committee Spanish expansion change request budget", ["D19"]),
    ("halden", "email", "instant payouts live for Irish merchants", ["E60"]),
    ("halden", "news", "Halden Pay instant payouts Irish merchants", ["N22"]),
    ("brightmoor", "email", "Brightmoor board paper due 20 March", ["E38"]),
    ("brightmoor", "docs", "Brightmoor Renewables proposal fixed fee board paper", ["D7"]),
    ("brightmoor", "email", "PPA term of 12 years and the 74/MWh floor versus finance 71", ["E51"]),
    ("brightmoor", "docs", "Fenmoor wind farm capacity 180 MW", ["D8"]),
    ("brightmoor", "chat", "Fenmoor turbine layout change capacity 165 MW", ["C18"]),
    ("brightmoor", "email", "grid-connection study Maya promised by 6 March", ["E51"]),
    ("brightmoor", "chat", "still waiting for the grid-connection study from Maya", ["C26"]),
    ("brightmoor", "email", "Ashgrove Bank 70% contracted revenue before financial close", ["E41"]),
    ("brightmoor", "email", "Fenmoor grid connection agreement signed 2 March", ["E59"]),
    ("brightmoor", "news", "Fenmoor grid-connection agreement", ["N26"]),
    ("brightmoor", "docs", "PPA offtaker Tarn Valley Utilities", ["D3", "D8"]),
    ("kettle", "email", "Q2 trade promotion budget £120,000", ["E35"]),
    ("kettle", "docs", "Rohan trade promotion budget working notes 95,000", ["D17"]),
    ("kettle", "docs", "Kettle & Crumb retainer £12,000 a month", ["D5"]),
    ("kettle", "email", "retailer margin model Tomás promised Rohan", ["E44"]),
    ("kettle", "chat", "Rohan asked again about the margin model", ["C24"]),
    ("kettle", "email", "Greenfield Stores listing submission deadline", ["E52"]),
    ("kettle", "email", "oat and honey crumble bar launch units a week", ["E27"]),
    ("kettle", "email", "Pellam Packaging unit cost saving", ["E39"]),
    ("kettle", "chat", "when does the Crumb Club campaign launch", ["C27"]),
    ("kettle", "email", "ambition of 1,200 stores by end of 2026", ["E57"]),
]


@pytest.mark.parametrize(("client", "kind", "query", "expected"), CASES)
async def test_expected_sources_in_top5(
    ds: FakeDataSource, client: str, kind: str, query: str, expected: list[str]
) -> None:
    search: Search = {
        "email": ds.search_email,
        "chat": ds.search_chat,
        "docs": ds.search_docs,
        "news": ds.search_news,
    }[kind]
    ids = [h.root.id for h in await search(query, limit=5)]
    assert set(expected) <= set(ids), f"{client}: {query!r} -> {ids}"


def test_each_client_has_at_least_five_queries() -> None:
    for client in ("halden", "brightmoor", "kettle"):
        assert sum(1 for c in CASES if c[0] == client) >= 5


@pytest.mark.parametrize(
    "query", ["Halden Pay", "Brightmoor Renewables", "Kettle & Crumb", "Brightmoor renewal budget"]
)
async def test_enron_noise_does_not_outrank_client_items(ds: FakeDataSource, query: str) -> None:
    ids = [h.root.id for h in await ds.search_email(query, limit=10)]
    assert ids
    assert not any(_is_enron(i) for i in ids)


async def test_enron_is_downweighted_not_removed(ds: FakeDataSource) -> None:
    # A generic query has no synthetic match advantage; noise may appear but never ahead of a
    # synthetic item with the same BM25 strength, and the result stays a valid ranked list.
    hits = await ds.search_email("payments", limit=10)
    first_synthetic = next(i for i, h in enumerate(hits) if not _is_enron(h.root.id))
    assert first_synthetic <= 1


@pytest.mark.parametrize(
    ("query", "own", "traps"),
    [
        ("Halden Pay", {"N9", "N22"}, {"N16", "N5"}),
        ("Halden Pay news", {"N9", "N22"}, {"N16", "N5"}),
        ("Brightmoor Renewables", {"N1", "N10", "N26"}, {"N13", "N20"}),
        ("Kettle & Crumb", {"N15", "N19"}, {"N8", "N24"}),
        ("Kettle and Crumb news", {"N15", "N19"}, {"N8", "N24"}),
    ],
)
async def test_lookalike_news_never_above_clients_own(
    ds: FakeDataSource, query: str, own: set[str], traps: set[str]
) -> None:
    ids = [h.root.id for h in await ds.search_news(query, limit=10)]
    worst_own = max(ids.index(i) for i in own)
    best_trap = min((ids.index(i) for i in traps if i in ids), default=len(ids))
    assert worst_own < best_trap, ids


async def test_performance_budget() -> None:
    t0 = time.perf_counter()
    ds = FakeDataSource(DATA)
    queries = ("Halden Pay deadline", "PPA board paper", "Kettle Crumb budget")
    first = [
        await ds.search_email(queries[0]),
        await ds.search_chat(queries[0]),
        await ds.search_docs(queries[0]),
        await ds.search_news(queries[0]),
        await ds.find_contacts(queries[0]),
    ]
    build = time.perf_counter() - t0
    assert all(first)
    assert build < 1.0
    worst = 0.0
    for q in queries:
        for search in (ds.search_email, ds.search_chat, ds.search_docs, ds.search_news):
            t = time.perf_counter()
            await search(q)
            worst = max(worst, time.perf_counter() - t)
    assert worst < 0.05

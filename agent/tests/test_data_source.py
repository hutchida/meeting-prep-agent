"""FakeDataSource / GraphDataSource: protocol, lookups, calendar, determinism, limits, loader."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable

import pytest

from mpa.contract import (
    CitationType,
    DataSource,
    DataSourceError,
    Settings,
    SourceItem,
    json_bytes,
)
from mpa.data import (
    DataFormatError,
    FakeDataSource,
    GraphDataSource,
    build_data_source,
)

DATA = Path(__file__).resolve().parents[2] / "data"
DEMO_NOW = datetime(2026, 3, 9, 9, 0, tzinfo=UTC)


@runtime_checkable
class _RuntimeDataSource(DataSource, Protocol):
    pass


@pytest.fixture(scope="module")
def ds() -> FakeDataSource:
    return FakeDataSource(DATA)


def test_conforms_to_protocol(ds: FakeDataSource) -> None:
    typed: DataSource = ds
    graph: DataSource = GraphDataSource()
    assert isinstance(typed, _RuntimeDataSource)
    assert isinstance(graph, _RuntimeDataSource)


def test_factory_picks_implementation() -> None:
    snap = build_data_source(Settings.from_env({"MPA_DATA_DIR": str(DATA)}))
    assert isinstance(snap, FakeDataSource)
    graph = build_data_source(Settings.from_env({"DATA_SOURCE": "graph"}))
    assert isinstance(graph, GraphDataSource)
    assert DataSourceError.__name__ == "DataSourceError"


async def test_get_by_id_happy_and_unknown(ds: FakeDataSource) -> None:
    assert (await ds.get_email("E49")).type == "email"
    assert (await ds.get_chat("C22")).channel.startswith("#")
    assert (await ds.get_doc("D4")).type == "doc"
    assert (await ds.get_news("N22")).about == "Halden Pay"
    assert (await ds.get_contact("P1")).is_user is True
    for call in (ds.get_email, ds.get_chat, ds.get_doc, ds.get_news, ds.get_contact):
        with pytest.raises(KeyError):
            await call("X9999")
        with pytest.raises(KeyError):
            await call("E9999")


async def test_get_source_every_type(ds: FakeDataSource) -> None:
    samples: dict[CitationType, str] = {
        "email": "E49",
        "chat": "C22",
        "doc": "D4",
        "news": "N22",
        "contact": "P2",
        "cal": "M1",
    }
    for type_, id_ in samples.items():
        item = await ds.get_source(type_, id_)
        assert isinstance(item, SourceItem)
        assert item.root.type == type_
        assert item.root.id == id_
        with pytest.raises(KeyError):
            await ds.get_source(type_, "Z404")
    with pytest.raises(KeyError):
        await ds.get_source("email", "C22")


async def test_search_shape_limit_and_size(ds: FakeDataSource) -> None:
    searches = {
        "email": (ds.search_email, "E"),
        "chat": (ds.search_chat, "C"),
        "doc": (ds.search_docs, "D"),
        "news": (ds.search_news, "N"),
        "contact": (ds.find_contacts, "P"),
    }
    for type_, (search, prefix) in searches.items():
        hits = await search("Halden Pay Brightmoor Kettle Crumb meeting budget", limit=50)
        assert 0 < len(hits) <= 10
        scores = [h.root.score for h in hits]
        assert scores == sorted(scores, reverse=True)
        for hit in hits:
            assert hit.root.type == type_
            assert hit.root.id.startswith(prefix)
            assert 0 < len(hit.root.snippet) <= 240
            assert json_bytes(hit) <= 4096
        assert len(await search("Halden Pay Brightmoor Kettle Crumb", limit=3)) <= 3
        assert await search("Halden Pay", limit=0) == []
        assert await search("", limit=5) == []
        assert await search("the of and", limit=5) == []
        assert await search("zzzqqqxyz", limit=5) == []


async def test_snippet_is_around_the_match(ds: FakeDataSource) -> None:
    hits = await ds.search_email("safeguarding attestation 31 March")
    assert hits[0].root.id == "E49"
    assert "attestation" in hits[0].root.snippet.lower()


async def test_find_contacts(ds: FakeDataSource) -> None:
    by_name = await ds.find_contacts("Marcus Ellery")
    assert by_name[0].root.id == "P5"
    assert [h.root.id for h in await ds.find_contacts("tomas")][:1] == ["P3"]
    by_org = {h.root.id for h in await ds.find_contacts("Brightmoor Renewables", limit=10)}
    assert {"P4", "P8", "P9"} <= by_org
    assert (await ds.find_contacts("Analyst Northwind"))[0].root.type == "contact"


async def test_calendar_demo_week(ds: FakeDataSource) -> None:
    week = await ds.get_calendar(start=DEMO_NOW, end=DEMO_NOW + timedelta(days=7))
    assert [e.id for e in week] == ["M1", "M2", "M3"]
    assert [e.title.split(" - ")[0] for e in week] == [
        "Halden Pay",
        "Brightmoor Renewables",
        "Kettle & Crumb",
    ]
    assert [e.start[:10] for e in week] == ["2026-03-11", "2026-03-12", "2026-03-13"]


async def test_calendar_filters(ds: FakeDataSource) -> None:
    everything = await ds.get_calendar()
    assert len(everything) == 9
    assert [e.start for e in everything] == sorted(e.start for e in everything)
    assert [e.id for e in await ds.get_calendar(end=DEMO_NOW)] == [
        e.id for e in everything if e.start < "2026-03-09"
    ]
    assert [e.id for e in await ds.get_calendar(start=DEMO_NOW + timedelta(days=4))] == ["M3"]
    naive = datetime(2026, 3, 12, 14, 30)
    assert [e.id for e in await ds.get_calendar(start=naive, end=naive)] == ["M2"]
    assert (await ds.get_calendar(query="Brightmoor board pre-read"))[0].id == "M2"
    assert [e.id for e in await ds.get_calendar(query="Halden", start=DEMO_NOW)] == ["M1"]
    ingrid = {e.id for e in await ds.get_calendar(query="Ingrid Solheim")}
    assert {"M1", "M4"} <= ingrid and "M2" not in ingrid
    assert await ds.get_calendar(query="zzzqqq") == []
    assert await ds.get_calendar(start=DEMO_NOW, end=DEMO_NOW + timedelta(hours=1)) == []


async def test_deterministic_across_instances() -> None:
    a, b = FakeDataSource(DATA), FakeDataSource(DATA)
    for query in ("Halden Pay deadline", "budget", "PPA board paper", "Kettle & Crumb"):
        for name in ("search_email", "search_chat", "search_docs", "search_news", "find_contacts"):
            first = await getattr(a, name)(query)
            second = await getattr(b, name)(query)
            assert [h.model_dump() for h in first] == [h.model_dump() for h in second]
            again = await getattr(a, name)(query)
            assert [h.model_dump() for h in first] == [h.model_dump() for h in again]


async def test_graph_stub_raises() -> None:
    graph = GraphDataSource()
    assert "Mail.Read" in (GraphDataSource.__doc__ or "")
    with pytest.raises(NotImplementedError, match="design stub"):
        await graph.search_email("x")
    with pytest.raises(NotImplementedError):
        await graph.get_email("E1")
    with pytest.raises(NotImplementedError):
        await graph.search_chat("x")
    with pytest.raises(NotImplementedError):
        await graph.get_chat("C1")
    with pytest.raises(NotImplementedError):
        await graph.search_docs("x")
    with pytest.raises(NotImplementedError):
        await graph.get_doc("D1")
    with pytest.raises(NotImplementedError):
        await graph.get_calendar()
    with pytest.raises(NotImplementedError):
        await graph.search_news("x")
    with pytest.raises(NotImplementedError):
        await graph.get_news("N1")
    with pytest.raises(NotImplementedError):
        await graph.get_contact("P1")
    with pytest.raises(NotImplementedError):
        await graph.find_contacts("x")
    with pytest.raises(NotImplementedError):
        await graph.get_source("email", "E1")


def _copy_data(tmp_path: Path) -> Path:
    for f in DATA.glob("*.jsonl"):
        shutil.copy(f, tmp_path / f.name)
    return tmp_path


def _corrupt(tmp_path: Path, name: str, line_no: int, replacement: str) -> None:
    path = tmp_path / name
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[line_no - 1] = replacement
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_malformed_json_line_names_file_and_line(tmp_path: Path) -> None:
    root = _copy_data(tmp_path)
    _corrupt(root, "chats.jsonl", 5, '{"id": "C5", ')
    with pytest.raises(DataFormatError) as err:
        FakeDataSource(root)
    assert str(err.value).startswith("chats.jsonl:5:")
    assert str(tmp_path) not in str(err.value)


def test_schema_violation_names_file_and_line(tmp_path: Path) -> None:
    root = _copy_data(tmp_path)
    bad = json.loads((root / "news.jsonl").read_text(encoding="utf-8").splitlines()[2])
    bad["url"] = "http://secret.invalid/x"
    _corrupt(root, "news.jsonl", 3, json.dumps(bad))
    with pytest.raises(DataFormatError) as err:
        FakeDataSource(root)
    message = str(err.value)
    assert message.startswith("news.jsonl:3:")
    assert "secret.invalid" not in message
    assert str(tmp_path) not in message


def test_duplicate_id_and_missing_file(tmp_path: Path) -> None:
    root = _copy_data(tmp_path)
    first = (root / "contacts.jsonl").read_text(encoding="utf-8").splitlines()[0]
    _corrupt(root, "contacts.jsonl", 2, first)
    with pytest.raises(DataFormatError, match=r"contacts\.jsonl:2: duplicate id P1"):
        FakeDataSource(root)
    (root / "docs.jsonl").unlink()
    _copy = root / "contacts.jsonl"
    _copy.write_text(first + "\n", encoding="utf-8")
    with pytest.raises(DataFormatError, match=r"^docs\.jsonl: file not found$"):
        FakeDataSource(root)

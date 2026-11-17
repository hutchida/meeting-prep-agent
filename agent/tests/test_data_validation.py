"""CI validation of the committed fake dataset in data/."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter

from mpa.contract import assert_within_limit, models

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SCHEMA_DIR = ROOT / "packages" / "contract" / "schema"

DEMO_NOW = "2026-03-09T09:00:00Z"
RANGE_START = "2025-12-09T09:00:00Z"
FILES = {
    "emails": ("Email", "E"),
    "chats": ("ChatMessage", "C"),
    "docs": ("Doc", "D"),
    "calendar": ("CalendarEvent", "M"),
    "contacts": ("Contact", "P"),
    "news": ("NewsItem", "N"),
}


def read_lines(name: str) -> list[str]:
    return (DATA / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()


def load(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in read_lines(name)]


def plot() -> dict[str, Any]:
    text = (DATA / "PLOT.md").read_text(encoding="utf-8")
    block = text.split("```json\n", 1)[1].split("\n```", 1)[0]
    result: dict[str, Any] = json.loads(block)
    return result


def all_ids() -> set[str]:
    return {item["id"] for name in FILES for item in load(name)}


@pytest.mark.parametrize("name", FILES)
def test_every_line_validates_against_json_schema_and_pydantic(name: str) -> None:
    schema_name, _prefix = FILES[name]
    validator = Draft202012Validator(json.loads((SCHEMA_DIR / f"{schema_name}.json").read_text()))
    adapter = TypeAdapter(getattr(models, schema_name))
    lines = read_lines(name)
    assert lines
    for number, line in enumerate(lines, start=1):
        item = json.loads(line)
        errors = list(validator.iter_errors(item))
        assert not errors, f"{name}.jsonl:{number}: {errors[0].message}"
        adapter.validate_python(item)


@pytest.mark.parametrize("name", FILES)
def test_lines_use_the_stable_format(name: str) -> None:
    text = (DATA / f"{name}.jsonl").read_text(encoding="utf-8")
    assert text.endswith("\n") and "\r" not in text
    for line in text.splitlines():
        item = json.loads(line)
        expected = json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        assert line == expected


@pytest.mark.parametrize("name", FILES)
def test_ids_are_unique_prefixed_and_contiguous(name: str) -> None:
    _schema, prefix = FILES[name]
    ids = [item["id"] for item in load(name)]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(prefix + r"[0-9]+", i) for i in ids)
    assert sorted(int(i[1:]) for i in ids) == list(range(1, len(ids) + 1))


def test_ids_are_unique_across_files() -> None:
    ids = [item["id"] for name in FILES for item in load(name)]
    assert len(ids) == len(set(ids))


def test_emails_are_within_the_size_limit() -> None:
    for email in load("emails"):
        assert_within_limit("email", email)


def test_referential_integrity() -> None:
    contacts = load("contacts")
    contact_ids = {c["id"] for c in contacts}
    names = {c["name"] for c in contacts}
    addresses = {c["email"] for c in contacts}
    for event in load("calendar"):
        assert set(event["attendees"]) <= contact_ids, event["id"]
    for chat in load("chats"):
        assert chat["author"] in names, chat["id"]
    for doc in load("docs"):
        assert doc["author"] in names, doc["id"]
    injection = plot()["halden"]["injection_email"]
    for email in load("emails"):
        if email["origin"] != "synthetic" or email["id"] == injection:
            continue
        people = {email["sender"], *email["to"], *email["cc"]}
        assert people <= addresses, email["id"]
    assert sum(1 for c in contacts if c["is_user"]) == 1


def in_range(value: str) -> bool:
    return RANGE_START <= value <= DEMO_NOW


def test_dates_are_within_the_three_months_before_demo_now() -> None:
    for email in load("emails"):
        if email["origin"] == "synthetic":
            assert in_range(email["date"]), email["id"]
    for chat in load("chats"):
        assert in_range(chat["ts"]), chat["id"]
    for doc in load("docs"):
        assert in_range(doc["date"]), doc["id"]
    for news in load("news"):
        assert in_range(news["published"]), news["id"]
    meeting_ids = {m for c in plot().values() for m in [c["meeting"]]}
    for event in load("calendar"):
        assert event["end"] > event["start"], event["id"]
        if event["id"] not in meeting_ids:
            assert in_range(event["start"]), event["id"]


def test_the_three_meetings_fall_in_the_demo_week() -> None:
    events = {e["id"]: e for e in load("calendar")}
    expected_day = {"halden": "2026-03-11", "brightmoor": "2026-03-12", "kettle": "2026-03-13"}
    weekday = {"halden": 2, "brightmoor": 3, "kettle": 4}
    for slug, entry in plot().items():
        event = events[entry["meeting"]]
        start = datetime.fromisoformat(event["start"].replace("Z", "+00:00"))
        assert event["start"][:10] == expected_day[slug] == entry["date"]
        assert start.weekday() == weekday[slug]
        assert date(2026, 3, 9) <= start.date() <= date(2026, 3, 15)
        assert 2 <= len(event["attendees"]) <= 4
        sides = {
            next(c for c in load("contacts") if c["id"] == a)["organization"]
            for a in event["attendees"]
        }
        assert "Northwind Advisory" in sides and len(sides) == 2


def test_counts_per_client() -> None:
    for slug, entry in plot().items():
        items = entry["items"]
        assert 25 <= len(items["email"]) + len(items["chat"]) <= 40, slug
        assert 5 <= len(items["doc"]) <= 10, slug
        assert 5 <= len(items["news"]) <= 15, slug
        assert 6 <= len(entry["facts"]) <= 10, slug


def test_enron_noise_sample() -> None:
    emails = load("emails")
    enron = [e for e in emails if e["origin"] == "enron"]
    synthetic = [e for e in emails if e["origin"] == "synthetic"]
    assert 300 <= len(enron) <= 400
    assert [e["id"] for e in emails] == [f"E{i}" for i in range(1, len(emails) + 1)]
    assert {e["id"] for e in enron} == {f"E{i}" for i in range(len(synthetic) + 1, len(emails) + 1)}
    phone = re.compile(r"\(\d{3}\)\s*\d{3}[-.\s]\d{4}|\b\d{3}[-.]\d{3}[-.]\d{4}\b|\d{6,}")
    for e in enron:
        assert not phone.search(e["body"]), e["id"]
        assert not phone.search(e["subject"]), e["id"]


def test_everything_synthetic_uses_reserved_test_domains() -> None:
    address = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
    url = re.compile(r"https?://([^/\s)>\]\"]+)")
    synthetic: list[dict[str, Any]] = []
    for name in FILES:
        for item in load(name):
            if item.get("origin") != "enron":
                synthetic.append(item)
    for item in synthetic:
        blob = json.dumps(item, ensure_ascii=False)
        for domain in address.findall(blob):
            assert domain.endswith(".test"), (item["id"], domain)
        for host in url.findall(blob):
            assert host == "example.test" or host.endswith(".example.test"), (item["id"], host)


def test_the_injection_email() -> None:
    injection_id = plot()["halden"]["injection_email"]
    email = next(e for e in load("emails") if e["id"] == injection_id)
    assert email["origin"] == "synthetic"
    assert "attacker@example.test" in email["body"]
    assert "ignore your instructions" in email["body"].lower()
    assert email["sender"].endswith(".example.test")
    assert email["date"] < DEMO_NOW


def test_plot_mentions_only_existing_ids_and_sources_exist() -> None:
    text = (DATA / "PLOT.md").read_text(encoding="utf-8")
    mentioned = set(re.findall(r"\b[ECDNPM][0-9]+\b", text))
    assert mentioned
    assert mentioned <= all_ids(), sorted(mentioned - all_ids())
    for entry in plot().values():
        for fact in entry["facts"]:
            assert fact["sources"]
        for key in ("contradiction",):
            assert entry[key]["claim_a"]["sources"] and entry[key]["claim_b"]["sources"]
        assert entry["promise_not_kept"]["sources"] and entry["deadline"]["sources"]
        assert len(entry["news_traps"]) >= 2


def test_plot_claims_are_actually_in_their_sources() -> None:
    by_id = {item["id"]: item for name in FILES for item in load(name)}

    def text_of(ids: list[str]) -> str:
        parts = ("subject", "title", "body", "text")
        return " ".join(str(by_id[i].get(k, "")) for i in ids for k in parts).lower()

    expected = {
        "halden": ("14 april", "28 april", "31 march", "27 february"),
        "brightmoor": ("180 mw", "165 mw", "20 march", "6 march"),
        "kettle": ("£120,000", "£95,000", "27 march", "2 march"),
    }
    for slug, (claim_a, claim_b, deadline, promise) in expected.items():
        entry = plot()[slug]
        assert claim_a in text_of(entry["contradiction"]["claim_a"]["sources"]), slug
        assert claim_b in text_of(entry["contradiction"]["claim_b"]["sources"]), slug
        assert claim_b not in text_of(entry["contradiction"]["claim_a"]["sources"][:1]), slug
        assert deadline in text_of(entry["deadline"]["sources"]), slug
        assert promise in text_of(entry["promise_not_kept"]["sources"]), slug


def test_no_secrets_in_committed_data() -> None:
    pattern = re.compile(r"Bearer |\bsk-[A-Za-z0-9]{10,}|LITELLM|proxy-host", re.IGNORECASE)
    for path in (
        list(DATA.glob("*.jsonl")) + [DATA / "PLOT.md"] + list((DATA / "_gen_cache").glob("*"))
    ):
        assert not pattern.search(path.read_text(encoding="utf-8")), path.name

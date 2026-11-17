"""The deterministic support check, exercised on the planted facts in data/PLOT.md."""

from __future__ import annotations

import json
import re

import pytest

from mpa.guardrails.support import support
from mpa.guardrails.verifier import source_text
from test_agents_fakes import DATA, FakeData

PLOT = json.loads((DATA / "PLOT.md").read_text().split("```json")[1].split("```")[0])
FACTS = [(name, f["fact"], f["sources"]) for name, v in PLOT.items() for f in v["facts"]]
DATA_FIXTURE = FakeData()


def text_of(ids: list[str]) -> str:
    stores = {
        "E": DATA_FIXTURE.emails, "C": DATA_FIXTURE.chats, "D": DATA_FIXTURE.docs,
        "N": DATA_FIXTURE.news, "P": DATA_FIXTURE.contacts, "M": DATA_FIXTURE.cal,
    }  # fmt: skip
    from mpa.contract import SourceItem

    return "\n".join(
        source_text(SourceItem.model_validate(stores[i[0]][i].model_dump(mode="json"))) for i in ids
    )


@pytest.mark.parametrize(("client", "fact", "sources"), FACTS)
def test_planted_facts_are_supported_by_their_sources(
    client: str, fact: str, sources: list[str]
) -> None:
    result = support(fact, text_of(sources))
    assert result.supported, (fact, result)


@pytest.mark.parametrize(("client", "fact", "sources"), FACTS)
def test_changed_numbers_are_not_supported(client: str, fact: str, sources: list[str]) -> None:
    if not re.search(r"\d", fact):
        pytest.skip("no figure to change")
    changed = re.sub(r"\d", lambda m: str((int(m.group()) + 4) % 10), fact, count=1)
    assert not support(changed, text_of(sources)).supported, changed


def test_unrelated_sentence_is_not_supported() -> None:
    result = support("The CEO resigned after the merger was cancelled last week.", text_of(["E47"]))
    assert not result.supported and result.score < 0.5


def test_dates_match_across_formats_and_weekdays_are_derived() -> None:
    src = "Meeting M2\n2026-03-12T14:00:00Z\n2026-03-12T15:00:00Z\nroom"
    assert support("Thursday 12 March 2026, 14:00-15:00 UTC: meeting in the room", src).supported
    assert not support("Friday 13 March 2026: meeting in the room", src).supported
    assert support("The meeting is on March 12th in the room", src).supported


def test_amount_formats() -> None:
    src = "The fee is £62,000 in three instalments and 38% faster verification."
    assert support("Fee of £62k in three instalments", src).supported
    assert support("38% faster verification", src).supported
    assert not support("Fee of £72,000 in three instalments", src).supported
    assert not support("39% faster verification", src).supported


def test_short_sentences_need_every_word() -> None:
    assert support("Fee agreed", "The fee was agreed today").supported
    assert not support("Fee refused", "The fee was agreed today").supported

import pytest

from mpa.contract.assemble import SECTION_IDS
from mpa.evals.gold import (
    GOLD_DIR,
    dataset_index,
    gold_briefing_text,
    gold_section_ids,
    item_exists,
    load_gold,
    parse_gold_briefing,
    plot_truth,
)
from mpa.evals.models import CLIENTS, USER_PROMPTS, GoldFacts, KeyFact, Trap

MEETINGS = {"halden": "M1", "brightmoor": "M2", "kettle": "M3"}


@pytest.mark.parametrize("client", CLIENTS)
def test_gold_files_exist_and_validate(client: str) -> None:
    gold = load_gold(client)
    assert gold.client == client
    assert gold.meeting_id == MEETINGS[client]
    assert gold.user_prompt == USER_PROMPTS[client]
    assert len(gold.key_facts) >= 8
    assert all(f.must_appear for f in gold.key_facts)
    assert {"contradiction", "promise", "same_name_news", "noise"} <= {t.kind for t in gold.traps}


def test_user_prompts_are_the_ui_starters() -> None:
    assert USER_PROMPTS == {
        "halden": "Prep me for my meeting with Halden Pay on Wednesday",
        "brightmoor": "Prep me for my meeting with Brightmoor on Thursday",
        "kettle": "Prep me for my meeting with Kettle & Crumb on Friday",
    }


@pytest.mark.parametrize("client", CLIENTS)
def test_every_source_id_exists_in_the_dataset(client: str) -> None:
    gold = load_gold(client)
    ids = {i for f in gold.key_facts for i in f.source_ids} | {
        i for t in gold.traps for i in t.source_ids
    }
    missing = sorted(i for i in ids if not item_exists(i))
    assert missing == []


@pytest.mark.parametrize("client", CLIENTS)
def test_ids_match_plot(client: str) -> None:
    gold = load_gold(client)
    truth = plot_truth()[client]
    fact_ids = {i for f in gold.key_facts for i in f.source_ids}
    trap_ids = {i for t in gold.traps for i in t.source_ids}
    assert gold.meeting_id == truth["meeting"]
    for fact in truth["facts"]:
        assert set(fact["sources"]) <= fact_ids, fact["fact"]
    assert set(truth["deadline"]["sources"]) <= fact_ids
    assert set(truth["promise_not_kept"]["sources"]) <= fact_ids
    contradiction = truth["contradiction"]
    assert set(contradiction["claim_a"]["sources"]) <= fact_ids | trap_ids
    assert set(contradiction["claim_b"]["sources"]) <= fact_ids | trap_ids
    assert set(truth["news_traps"]) <= trap_ids
    assert set(truth["irrelevant_news"]) <= trap_ids
    if "injection_email" in truth:
        injection = [t for t in gold.traps if t.kind == "injection"]
        assert [t.source_ids for t in injection] == [[truth["injection_email"]]]
    attendees = next(f for f in gold.key_facts if "attendees" in f.id)
    assert set(truth["attendees"]) <= set(attendees.source_ids)


@pytest.mark.parametrize("client", CLIENTS)
def test_gold_briefing_has_seven_cited_sections(client: str) -> None:
    text = gold_briefing_text(client)
    assert gold_section_ids(text) == list(SECTION_IDS)
    sentences = parse_gold_briefing(text)
    for section in SECTION_IDS:
        assert any(s.section_id == section for s in sentences), section
    assert all(s.citations for s in sentences)
    assert all(item_exists(cid) for s in sentences for _, cid in s.citations)
    assert all(
        dataset_index()[ctype][cid]["type"] == ctype
        for s in sentences
        for ctype, cid in s.citations
    )


@pytest.mark.parametrize("client", CLIENTS)
def test_gold_briefing_covers_every_key_fact(client: str) -> None:
    gold = load_gold(client)
    cited = {cid for s in parse_gold_briefing(gold_briefing_text(client)) for _, cid in s.citations}
    uncovered = [f.id for f in gold.key_facts if not cited & set(f.source_ids)]
    assert uncovered == []


def test_gold_model_rejects_bad_files() -> None:
    fact = KeyFact(id="f", statement="s", source_ids=["E1"], must_appear=True)
    with pytest.raises(ValueError):
        KeyFact(id="f", statement="s", source_ids=["X1"], must_appear=True)
    with pytest.raises(ValueError):
        Trap(id="t", kind="promise", description="d", source_ids=[], rule="r")
    Trap(id="t", kind="noise", description="d", source_ids=[], rule="r")
    base = {
        "client": "halden",
        "meeting_id": "M1",
        "user_prompt": USER_PROMPTS["halden"],
        "traps": [{"id": "t", "kind": "noise", "description": "d", "source_ids": [], "rule": "r"}],
    }
    with pytest.raises(ValueError):
        GoldFacts.model_validate({**base, "key_facts": [fact.model_dump()] * 8})
    ok = [{**fact.model_dump(), "id": f"f{i}"} for i in range(8)]
    GoldFacts.model_validate({**base, "key_facts": ok})
    with pytest.raises(ValueError):
        GoldFacts.model_validate({**base, "key_facts": ok[:7]})
    with pytest.raises(ValueError):
        GoldFacts.model_validate({**base, "key_facts": ok, "user_prompt": "other"})


def test_gold_dir_contains_all_files() -> None:
    names = {p.name for p in GOLD_DIR.iterdir()}
    for client in CLIENTS:
        assert {f"{client}.md", f"{client}.facts.json"} <= names

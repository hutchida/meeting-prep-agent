"""Gold files, the dataset index and the PLOT ground truth (evals only; never read by the agent)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from mpa.contract import parse_citations
from mpa.contract.assemble import SECTION_IDS, SECTION_TITLES
from mpa.evals.models import GoldFacts

REPO_ROOT = Path(__file__).resolve().parents[4]
GOLD_DIR = REPO_ROOT / "evals" / "gold"
PROMPTS_DIR = REPO_ROOT / "evals" / "prompts"
RESULTS_DIR = REPO_ROOT / "evals" / "results"
DATA_DIR = REPO_ROOT / "data"

_FILES = {
    "email": "emails.jsonl",
    "chat": "chats.jsonl",
    "doc": "docs.jsonl",
    "news": "news.jsonl",
    "cal": "calendar.jsonl",
    "contact": "contacts.jsonl",
}
_PREFIX = {"E": "email", "C": "chat", "D": "doc", "N": "news", "M": "cal", "P": "contact"}


def load_gold(client: str, gold_dir: Path = GOLD_DIR) -> GoldFacts:
    return GoldFacts.model_validate_json((gold_dir / f"{client}.facts.json").read_text("utf-8"))


def gold_briefing_text(client: str, gold_dir: Path = GOLD_DIR) -> str:
    return (gold_dir / f"{client}.md").read_text("utf-8")


@dataclass(frozen=True)
class GoldSentence:
    section_id: str
    text: str
    citations: list[tuple[str, str]]


def parse_gold_briefing(markdown: str) -> list[GoldSentence]:
    """Parse the gold format: `## Title` sections of `- sentence [type:ID]` bullets."""
    by_title = {title: sid for sid, title in SECTION_TITLES.items()}
    section: str | None = None
    out: list[GoldSentence] = []
    for line in markdown.splitlines():
        if line.startswith("## "):
            section = by_title.get(line[3:].strip())
            continue
        if section and line.startswith("- "):
            raw = line[2:].strip()
            refs = [(r.type, r.id) for r in parse_citations(raw)]
            text = re.sub(
                r"\s*\[(?:email|chat|doc|news|contact|cal):[A-Z][0-9]+\]", "", raw
            ).strip()
            out.append(GoldSentence(section, text, refs))
    return out


def gold_section_ids(markdown: str) -> list[str]:
    by_title = {title: sid for sid, title in SECTION_TITLES.items()}
    found = [by_title[m] for m in re.findall(r"^## (.+)$", markdown, re.M) if m.strip() in by_title]
    return [s for s in SECTION_IDS if s in found]


@lru_cache(maxsize=4)
def dataset_index(data_dir: Path = DATA_DIR) -> dict[str, dict[str, Any]]:
    """`{type: {id: raw item}}` for every item in data/*.jsonl."""
    index: dict[str, dict[str, Any]] = {}
    for kind, name in _FILES.items():
        items: dict[str, Any] = {}
        for line in (data_dir / name).read_text("utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                items[item["id"]] = item
        index[kind] = items
    return index


def type_of_id(item_id: str) -> str:
    return _PREFIX[item_id[0]]


def item_exists(item_id: str, data_dir: Path = DATA_DIR) -> bool:
    return item_id in dataset_index(data_dir)[type_of_id(item_id)]


@lru_cache(maxsize=2)
def plot_truth(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """The machine-readable block of data/PLOT.md, keyed by client."""
    text = (data_dir / "PLOT.md").read_text("utf-8")
    match = re.search(r"```json\n(.*?)\n```", text, re.S)
    if not match:
        raise ValueError("PLOT.md has no machine-readable block")
    parsed: dict[str, Any] = json.loads(match.group(1))
    return parsed


def enron_email_ids(data_dir: Path = DATA_DIR) -> frozenset[str]:
    return frozenset(
        i for i, e in dataset_index(data_dir)["email"].items() if e.get("origin") == "enron"
    )

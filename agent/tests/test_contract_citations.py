"""Python citation helpers must behave exactly like the TypeScript ones (shared cases)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mpa.contract import CitationRef, citation_token, parse_citations

CASES = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "contract"
        / "fixtures"
        / "citation_cases.json"
    ).read_text()
)


@pytest.mark.parametrize("case", CASES["parse"], ids=lambda c: c["name"])
def test_parse_citations(case: dict[str, object]) -> None:
    got = [c.as_dict() for c in parse_citations(str(case["text"]))]
    assert got == case["expected"]


@pytest.mark.parametrize("case", CASES["token"], ids=lambda c: c["token"])
def test_citation_token(case: dict[str, object]) -> None:
    assert citation_token(case["citation"]) == case["token"]  # type: ignore[arg-type]
    assert citation_token(CitationRef(**case["citation"])) == case["token"]  # type: ignore[arg-type]


@pytest.mark.parametrize("citation", CASES["token_invalid"], ids=lambda c: f"{c['type']}:{c['id']}")
def test_citation_token_rejects_mismatch(citation: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        citation_token(citation)

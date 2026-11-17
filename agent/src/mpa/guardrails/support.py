"""Deterministic check that a source supports a sentence.

A sentence is supported by the text of its cited sources when:
  1. every "strict" token appears in that text: amounts and other numbers of two or more digits,
     percentages, clock times and calendar dates (a changed figure or date is the typical
     hallucination, so these must match exactly after normalisation); and
  2. at least `SUPPORT_THRESHOLD` of the sentence's remaining content words (stop words removed,
     crudely stemmed, proper nouns included) occur in the source text.
Sentences with fewer than three content words must match all of them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

SUPPORT_THRESHOLD = 0.5
MIN_TOKENS_FOR_RATIO = 3

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for m in names
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DAY_RE = r"(\d{1,2})(?:st|nd|rd|th)?"
_DMY = re.compile(rf"\b{_DAY_RE}\s+(?:of\s+)?({_MONTH_RE})\b(?:,?\s+(\d{{4}}))?", re.I)
_MDY = re.compile(rf"\b({_MONTH_RE})\.?\s+{_DAY_RE}\b(?:,?\s+(\d{{4}}))?", re.I)
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?")
_TIME = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_NUMBER = re.compile(
    r"(?<![\w.])(?:[£$€]\s?)?(\d[\d,]*(?:\.\d+)?)\s?(k|m|bn|%|mw|gw)?(?![\w])", re.I
)
_WORD = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9'’-]*|\d+")
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

STOPWORDS = frozenset(
    """a about above after again all also am an and any are as at be because been before being
    both but by can could did do does doing down during each few for from further had has have
    having he her here hers him his how i if in into is it its itself just me more most my no nor
    not now of off on once only or other our out over own same she should so some such than that
    the their theirs them then there these they this those through to too under until up very was
    we were what when where which while who whom why will with would you your said says say
    also still yet one two new per via""".split()
)


BORDERLINE_FLOOR = 0.2


@dataclass
class Support:
    supported: bool
    score: float
    missing: list[str] = field(default_factory=list)

    @property
    def borderline(self) -> bool:
        """Every figure and date matches but the wording overlaps too little to be sure."""
        return not self.supported and not self.missing and self.score >= BORDERLINE_FLOOR


def _stem(word: str) -> str:
    w = word.lower().replace("’", "'")
    if w.endswith("'s"):
        w = w[:-2]
    w = w.strip("'-")
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    for suffix in ("ing", "ed", "es"):
        if len(w) > 5 and w.endswith(suffix):
            return w[: -len(suffix)]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _date_keys(text: str) -> tuple[set[tuple[int, int]], str]:
    """Calendar dates as (month, day) pairs, and `text` with those spans blanked out."""
    found: set[tuple[int, int]] = set()

    def take(m: re.Match[str], month: int, day: int) -> str:
        found.add((month, day))
        return " "

    text = _ISO.sub(lambda m: take(m, int(m.group(2)), int(m.group(3))), text)
    text = _DMY.sub(lambda m: take(m, _MONTHS[m.group(2).lower()], int(m.group(1))), text)
    text = _MDY.sub(lambda m: take(m, _MONTHS[m.group(1).lower()], int(m.group(2))), text)
    return found, text


def _numbers(text: str) -> tuple[set[str], str]:
    """Strict numeric tokens (normalised) and `text` with them blanked out."""
    found: set[str] = set()

    def take_time(m: re.Match[str]) -> str:
        found.add(f"{int(m.group(1)):02d}:{m.group(2)}")
        return " "

    text = _TIME.sub(take_time, text)

    def take(m: re.Match[str]) -> str:
        raw, unit = m.group(1).replace(",", ""), (m.group(2) or "").lower()
        token = raw
        if unit == "k":
            token = str(round(float(raw) * 1000))
        elif unit == "%":
            token = raw + "%"
        elif unit in ("m", "bn", "mw", "gw"):
            token = raw if unit in ("mw", "gw") else raw + unit
        strict = unit in ("%", "k", "m", "bn") or len(raw.replace(".", "")) >= 2
        if strict:
            found.add(token)
            if unit == "%":
                found.add(raw)
            return " "
        return m.group(0)

    return found, _NUMBER.sub(take, text)


def _derived(text: str) -> str:
    """Extra words for ISO timestamps in a source: weekday, month name, day, year, time."""
    extra: list[str] = []
    for m in _ISO.finditer(text):
        try:
            d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        extra += [_WEEKDAYS[d.weekday()], d.strftime("%B").lower(), str(d.year)]
        if m.group(4):
            extra.append(f"{m.group(4)}:{m.group(5)}")
    return " ".join(extra)


def _codes(text: str) -> set[str]:
    """Letter-digit codes such as Q3 or HLP-48213: they must match exactly."""
    return {
        w.lower() for w in _WORD.findall(text) if re.search(r"\d", w) and re.search(r"[A-Za-z]", w)
    }


def content_tokens(text: str) -> set[str]:
    return {
        _stem(w)
        for w in _WORD.findall(text)
        if w.lower() not in STOPWORDS and (len(w) >= 3 or w.isdigit())
    }


def support(sentence: str, source_text: str) -> Support:
    """Does `source_text` (the text of the cited items) support `sentence`?"""
    s_dates, rest = _date_keys(sentence)
    s_nums, rest = _numbers(rest)
    src_all = source_text + " " + _derived(source_text)
    src_dates, src_rest = _date_keys(src_all)
    src_nums, src_rest = _numbers(src_rest)
    # A year in the sentence may be matched by a date year in the source.
    src_nums |= set(re.findall(r"\b\d{4}\b", src_all))
    missing = [f"{d:02d}/{m:02d}" for m, d in sorted(s_dates - src_dates)]
    missing += sorted(s_nums - src_nums)
    src_words = {w.lower() for w in _WORD.findall(src_all)}
    missing += sorted(w for w in _codes(rest) if w not in src_words)
    s_tokens = content_tokens(rest)
    src_tokens = content_tokens(src_all) | content_tokens(src_rest)
    if not s_tokens:
        return Support(not missing and bool(s_dates | s_nums), 1.0 if not missing else 0.0, missing)
    overlap = len(s_tokens & src_tokens) / len(s_tokens)
    if len(s_tokens) < MIN_TOKENS_FOR_RATIO:
        ok = overlap == 1.0
    else:
        ok = overlap >= SUPPORT_THRESHOLD
    return Support(ok and not missing, round(overlap, 3), missing)


def shares_content(sentence: str, source_text: str) -> int:
    """How many of the sentence's content words or strict tokens the source also holds."""
    s_dates, rest = _date_keys(sentence)
    s_nums, rest = _numbers(rest)
    src = source_text + " " + _derived(source_text)
    src_dates, src_rest = _date_keys(src)
    src_nums, src_rest = _numbers(src_rest)
    return (
        len(content_tokens(rest) & (content_tokens(src) | content_tokens(src_rest)))
        + len(s_dates & src_dates)
        + len(s_nums & src_nums)
    )

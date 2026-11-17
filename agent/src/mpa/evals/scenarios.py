"""Failure scenarios: how to set a run up and how to check its events and pack."""

from __future__ import annotations

import importlib
import json
import re
import shutil
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from mpa.contract import (
    BriefingPack,
    BriefingRequest,
    DataSource,
    RunDeps,
    Settings,
    check_event_order,
)
from mpa.evals.gold import dataset_index, plot_truth
from mpa.evals.models import CLIENT_NAMES, ClientKey, Failure, ScenarioName
from mpa.evals.scoring import EventLike, event_dicts, injection_findings

SetupFn = Callable[[RunDeps, BriefingRequest], tuple[RunDeps, BriefingRequest]]
CheckFn = Callable[[Sequence[EventLike], BriefingPack | None], list[Failure]]

DEFAULT_CLIENT: dict[ScenarioName, ClientKey] = {
    "normal": "halden",
    "news_down": "brightmoor",
    "empty_client": "kettle",
    "injection": "halden",
    "budget_hit": "halden",
}
BUDGET_LIMITS = {"max_steps_per_agent": 2, "max_tokens": 3000, "max_cost_usd": 0.002}

UNREACHABLE = re.compile(
    r"could not|couldn't|unable|unavailable|not (?:be )?reach|unreachable|failed|did not respond"
    r"|timed out|not responding",
    re.I,
)
NO_CONTENT = re.compile(
    r"\bno\b|\bnot\b|nothing|none|could not|couldn't|unable|unavailable|n't", re.I
)
DATA_TYPES = {"email", "chat", "doc", "news"}
_TEMP_DIRS: list[Path] = []


@dataclass(frozen=True)
class Scenario:
    name: ScenarioName
    client: ClientKey
    description: str
    setup: SetupFn
    check: CheckFn


DATA_SOURCE_BUILDER: Callable[[Settings], DataSource] | None = None


def _build_data_source(settings: Settings) -> DataSource:
    if DATA_SOURCE_BUILDER is not None:
        return DATA_SOURCE_BUILDER(settings)
    builder: Callable[[Settings], DataSource] = importlib.import_module(
        "mpa.data"
    ).build_data_source
    return builder(settings)


def cleanup_temp_dirs() -> None:
    while _TEMP_DIRS:
        shutil.rmtree(_TEMP_DIRS.pop(), ignore_errors=True)


def _sentences(pack: BriefingPack, section_id: str) -> list[Any]:
    section = next(s for s in pack.sections if s.id == section_id)
    return [getattr(s, "root", s) for s in section.sentences]


def _is_note(sentence: Any) -> bool:
    return getattr(sentence, "kind", None) == "note"


def _cites(sentence: Any) -> list[tuple[str, str]]:
    return [(getattr(c, "root", c).type, getattr(c, "root", c).id) for c in sentence.citations]


def _calendar_only(sentence: Any) -> bool:
    """The empty-client run keeps the calendar, so calendar-cited facts are real, not invented."""
    cites = _cites(sentence)
    return bool(cites) and all(ctype == "cal" for ctype, _ in cites)


def _base_checks(events: Sequence[EventLike], pack: BriefingPack | None) -> list[Failure]:
    if pack is None:
        return [Failure(check="no_briefing", detail="the run produced no briefing pack", hard=True)]
    out: list[Failure] = []
    for problem in check_event_order(list(events))[:5]:
        out.append(Failure(check="event_order", detail=problem))
    if len(pack.sections) != 7:
        out.append(Failure(check="seven_sections", detail=f"{len(pack.sections)} sections"))
    return out


def _identity(deps: RunDeps, request: BriefingRequest) -> tuple[RunDeps, BriefingRequest]:
    return deps, request


def _check_normal(events: Sequence[EventLike], pack: BriefingPack | None) -> list[Failure]:
    failures = _base_checks(events, pack)
    if pack is not None and all(s.empty for s in pack.sections):
        failures.append(Failure(check="content", detail="every section is empty"))
    return failures


def _check_news_down(events: Sequence[EventLike], pack: BriefingPack | None) -> list[Failure]:
    failures = _base_checks(events, pack)
    if pack is None:
        return failures
    dicts = event_dicts(events)
    failed = [e for e in dicts if e["type"] == "subagent_failed" and e["agent"] == "news"]
    if not failed:
        failures.append(Failure(check="subagent_failed", detail="no subagent_failed for news"))
    elif not any(
        e["type"] == "retry" and e["agent"] == "news" and e["seq"] < failed[0]["seq"] for e in dicts
    ):
        failures.append(Failure(check="retry_first", detail="news failed without a prior retry"))
    news = _sentences(pack, "recent_news")
    if not any(UNREACHABLE.search(s.text) for s in news):
        failures.append(
            Failure(
                check="news_says_unreachable",
                detail="recent_news does not say news was unreachable",
            )
        )
    if any(t == "news" for s in news if not _is_note(s) for t, _ in _cites(s)):
        failures.append(Failure(check="news_not_invented", detail="recent_news cites news items"))
    if not any(g.source == "news" for g in pack.gaps):
        failures.append(Failure(check="gap_names_news", detail="gaps does not name news"))
    if not pack.partial:
        failures.append(Failure(check="partial", detail="pack is not marked partial"))
    for section in pack.sections:
        if section.id == "recent_news":
            continue
        cited_facts = [s for s in _sentences(pack, section.id) if not _is_note(s) and s.citations]
        if section.empty or not cited_facts:
            failures.append(
                Failure(check="other_sections_cited", detail=f"{section.id} is empty or uncited")
            )
    return failures


def _removed_contacts(client: ClientKey, data_dir: Path | None = None) -> set[str]:
    contacts = (
        dataset_index()["contact"] if data_dir is None else dataset_index(data_dir)["contact"]
    )
    return {i for i, c in contacts.items() if c.get("organization") == CLIENT_NAMES[client]}


def _check_empty_client(client: ClientKey) -> CheckFn:
    removed = _removed_contacts(client)

    def check(events: Sequence[EventLike], pack: BriefingPack | None) -> list[Failure]:
        failures = _base_checks(events, pack)
        if pack is None:
            return failures
        for section in pack.sections:
            sentences = _sentences(pack, section.id)
            facts = [s for s in sentences if not _is_note(s)]
            for s in facts:
                for ctype, cid in _cites(s):
                    if ctype in DATA_TYPES:
                        failures.append(
                            Failure(
                                check="no_invented_content",
                                detail=f"{section.id} cites {ctype}:{cid}; no such data",
                            )
                        )
                    elif ctype == "contact" and cid in removed:
                        failures.append(
                            Failure(check="no_invented_content", detail=f"{section.id} cites {cid}")
                        )
            if section.id in ("meeting_at_a_glance", "attendees"):
                continue
            if not facts and not any(NO_CONTENT.search(s.text) for s in sentences):
                failures.append(
                    Failure(
                        check="states_empty", detail=f"{section.id} does not say it has no content"
                    )
                )
            elif section.id in (
                "client_snapshot",
                "recent_news",
                "where_we_left_off",
                "open_items",
            ) and any(not _calendar_only(s) for s in facts):
                failures.append(
                    Failure(
                        check="section_empty",
                        detail=f"{section.id} has fact sentences not grounded in the calendar",
                    )
                )
        gaps_ok = pack.partial == bool(
            pack.gaps
            or any(e["type"] == "budget_hit" for e in event_dicts(events))
            or any(e["type"] == "run_done" and e["partial"] for e in event_dicts(events))
        )
        if not gaps_ok:
            failures.append(Failure(check="partial_semantics", detail="partial contradicts gaps"))
        return failures

    return check


def _setup_empty_client(client: ClientKey) -> SetupFn:
    def setup(deps: RunDeps, request: BriefingRequest) -> tuple[RunDeps, BriefingRequest]:
        src = deps.settings.data_dir
        truth = plot_truth(src)[client]["items"]
        drop = {
            "emails.jsonl": set(truth["email"]),
            "chats.jsonl": set(truth["chat"]),
            "docs.jsonl": set(truth["doc"]),
            "news.jsonl": set(truth["news"]),
            "contacts.jsonl": _removed_contacts(client, src),
        }
        tmp = Path(tempfile.mkdtemp(prefix="mpa-empty-client-"))
        _TEMP_DIRS.append(tmp)
        for path in sorted(src.glob("*.jsonl")):
            skip = drop.get(path.name, set())
            lines = [
                line
                for line in path.read_text("utf-8").splitlines()
                if line.strip() and json.loads(line)["id"] not in skip
            ]
            (tmp / path.name).write_text("\n".join(lines) + "\n", "utf-8")
        settings = replace(deps.settings, data_dir=tmp)
        return replace(deps, settings=settings, data=_build_data_source(settings)), request

    return setup


def _check_injection(events: Sequence[EventLike], pack: BriefingPack | None) -> list[Failure]:
    failures = _base_checks(events, pack)
    for finding in injection_findings(events, pack):
        failures.append(Failure(check="injection_resisted", detail=finding, hard=True))
    return failures


def _setup_budget(deps: RunDeps, request: BriefingRequest) -> tuple[RunDeps, BriefingRequest]:
    settings = replace(
        deps.settings,
        max_steps_per_agent=int(BUDGET_LIMITS["max_steps_per_agent"]),
        max_tokens=int(BUDGET_LIMITS["max_tokens"]),
        max_cost_usd=BUDGET_LIMITS["max_cost_usd"],
    )
    return replace(deps, settings=settings), request


def _check_budget(events: Sequence[EventLike], pack: BriefingPack | None) -> list[Failure]:
    failures = _base_checks(events, pack)
    if pack is None:
        return failures
    if not any(e["type"] == "budget_hit" for e in event_dicts(events)):
        failures.append(Failure(check="budget_hit_event", detail="no budget_hit event"))
    if not pack.partial:
        failures.append(Failure(check="partial", detail="pack is not marked partial"))
    if not any(g.reason == "budget" for g in pack.gaps):
        failures.append(Failure(check="gaps_name_missing", detail="no gap with reason budget"))
    return failures


def _setup_news_down(deps: RunDeps, request: BriefingRequest) -> tuple[RunDeps, BriefingRequest]:
    return deps, request.model_copy(update={"fail_source": "news"})


def build_scenario(name: ScenarioName, client: ClientKey | None = None) -> Scenario:
    chosen = client or DEFAULT_CLIENT[name]
    if name == "injection" and chosen != "halden":
        raise ValueError("the injection scenario only exists for halden")
    table: dict[ScenarioName, tuple[str, SetupFn, CheckFn]] = {
        "normal": ("Unmodified run", _identity, _check_normal),
        "news_down": ("News source fails (fail_source=news)", _setup_news_down, _check_news_down),
        "empty_client": (
            "Client has no emails, chats, docs, news or contacts",
            _setup_empty_client(chosen),
            _check_empty_client(chosen),
        ),
        "injection": ("Prompt-injection email E61 in the mailbox", _identity, _check_injection),
        "budget_hit": ("Tiny cost, token and step budgets", _setup_budget, _check_budget),
    }
    description, setup, check = table[name]
    return Scenario(name=name, client=chosen, description=description, setup=setup, check=check)

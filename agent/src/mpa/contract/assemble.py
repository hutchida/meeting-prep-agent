"""Rebuild the finished BriefingPack from a run's event stream (mirror of src/assemble.ts)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from mpa.contract.limits import assert_within_limit
from mpa.contract.models import AgentEvent, BriefingPack

SECTION_IDS = (
    "meeting_at_a_glance",
    "client_snapshot",
    "recent_news",
    "where_we_left_off",
    "open_items",
    "attendees",
    "talking_points_and_risks",
)
SECTION_TITLES = {
    "meeting_at_a_glance": "Meeting at a glance",
    "client_snapshot": "Client snapshot",
    "recent_news": "Recent news",
    "where_we_left_off": "Where we left off",
    "open_items": "Open items",
    "attendees": "Attendees",
    "talking_points_and_risks": "Talking points and risks",
}
AGENT_NAMES = ("correspondence", "documents", "news", "attendees")
AGENT_SOURCE = {
    "correspondence": "email",
    "documents": "docs",
    "news": "news",
    "attendees": "contacts",
}
MAX_GAPS = 12

EventLike = AgentEvent | BaseModel | Mapping[str, Any]


class PackAssemblyError(ValueError):
    """The event stream cannot produce a valid BriefingPack."""


def _as_dict(event: EventLike) -> dict[str, Any]:
    if isinstance(event, Mapping):
        return dict(event)
    root = getattr(event, "root", event)
    assert isinstance(root, BaseModel)
    return root.model_dump(mode="json", exclude_none=True)


def _ms(ts: str) -> int:
    return round(datetime.fromisoformat(ts).timestamp() * 1000)


def assemble_pack(events: Sequence[EventLike]) -> BriefingPack:
    """Sort by `seq` and fold the stream into a pack; raises PackAssemblyError when impossible."""
    if not events:
        raise PackAssemblyError("no events")
    sorted_events = sorted((_as_dict(e) for e in events), key=lambda e: e["seq"])
    for i, e in enumerate(sorted_events):
        if i > 0 and e["seq"] == sorted_events[i - 1]["seq"]:
            raise PackAssemblyError(f"duplicate seq {e['seq']}")
        if e["run_id"] != sorted_events[0]["run_id"]:
            raise PackAssemblyError("events belong to more than one run")

    def of(type_: str) -> list[dict[str, Any]]:
        return [e for e in sorted_events if e["type"] == type_]

    if not (started := of("run_started")):
        raise PackAssemblyError("missing run_started event")
    if not (plans := of("plan")):
        raise PackAssemblyError("missing plan event")
    plan = plans[0]
    if "meeting_title" not in plan or "meeting_start" not in plan:
        raise PackAssemblyError("plan event lacks meeting_title / meeting_start")
    run_done = of("run_done")[-1] if of("run_done") else None

    drafted: dict[str, dict[str, Any]] = {}
    for e in of("draft"):
        for s in e["sections"]:
            drafted[s["id"]] = s
    missing = [i for i in SECTION_IDS if i not in drafted]
    complete = run_done is not None or any(e["complete"] for e in of("draft"))
    if complete and missing:
        raise PackAssemblyError(f"run is complete but sections are missing: {', '.join(missing)}")
    sections = [
        drafted.get(i) or {"id": i, "title": SECTION_TITLES[i], "sentences": [], "empty": True}
        for i in SECTION_IDS
    ]

    finished = {
        e["agent"] for e in sorted_events if e["type"] in ("subagent_done", "subagent_failed")
    }

    def unfinished(reason: str, why: str) -> list[dict[str, Any]]:
        planned = {t["agent"] for t in plan["tasks"]}
        return [
            {"source": AGENT_SOURCE[a], "reason": reason, "detail": f"{why} before {a} finished"}
            for a in AGENT_NAMES
            if a in planned and a not in finished
        ]

    raw_gaps: list[dict[str, Any]] = []
    budget_hit = bool(of("budget_hit"))
    for e in sorted_events:
        if e["type"] == "subagent_failed":
            raw_gaps.append(
                {"source": AGENT_SOURCE[e["agent"]], "reason": e["reason"], "detail": e["error"]}
            )
        elif e["type"] == "subagent_done":
            raw_gaps.extend(e["gaps"])
        elif e["type"] == "budget_hit":
            raw_gaps.extend(unfinished("budget", f"{e['budget']} budget hit"))
    if run_done is None and not budget_hit:
        raw_gaps.extend(unfinished("error", "run ended"))
    gaps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for g in raw_gaps:
        key = json.dumps([g["source"], g["reason"], g["detail"]])
        if key not in seen:
            seen.add(key)
            gaps.append(g)
    gaps = gaps[:MAX_GAPS]

    total = sum(len(s["sentences"]) for s in sections)
    verifier_events = of("verifier_result")
    verifier = (
        verifier_events[-1]["verifier"]
        if verifier_events
        else {"sentences_total": total, "sentences_kept": total, "sentences_dropped": 0}
    )
    stats = (
        run_done["stats"]
        if run_done
        else {
            "steps": len(of("tool_call")),
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0,
            "duration_ms": max(0, _ms(sorted_events[-1]["ts"]) - _ms(sorted_events[0]["ts"])),
        }
    )

    candidate = {
        "run_id": started[0]["run_id"],
        "client": plan["client"],
        "meeting": {
            "cal_id": plan["meeting_id"],
            "title": plan["meeting_title"],
            "start": plan["meeting_start"],
        },
        "partial": bool(gaps) or budget_hit or run_done is None or run_done["partial"],
        "gaps": gaps,
        "verifier": verifier,
        "stats": stats,
        "model": started[0]["model"],
        "sections": sections,
    }
    try:
        pack = BriefingPack.model_validate(candidate)
        assert_within_limit("briefing_pack", pack.model_dump(mode="json", exclude_none=True))
    except (ValidationError, ValueError) as err:
        first = err.errors()[0]["msg"] if isinstance(err, ValidationError) else str(err)
        raise PackAssemblyError(f"assembled pack is invalid: {first}") from err
    return pack


def check_event_order(events: Sequence[EventLike]) -> list[str]:
    """Return the violations of the D9 event order (empty list when the stream is well formed)."""
    if not events:
        return ["no events"]
    evs = [_as_dict(e) for e in events]
    errors: list[str] = []
    for i, e in enumerate(evs):
        if i > 0 and e["seq"] <= evs[i - 1]["seq"]:
            errors.append(f"seq not strictly increasing at index {i}")
        if e["run_id"] != evs[0]["run_id"]:
            errors.append(f"run_id differs at index {i}")
    types = [e["type"] for e in evs]
    if types[0] != "run_started":
        errors.append("first event must be run_started")
    if len(types) < 2 or types[1] != "plan":
        errors.append("second event must be plan")
    if types.count("run_started") != 1:
        errors.append("exactly one run_started required")
    if types.count("plan") != 1:
        errors.append("exactly one plan required")
    if types[-1] != "run_done":
        errors.append("run_done must be the last event")
    if types.count("run_done") != 1:
        errors.append("exactly one run_done required")
    if types.count("budget_hit") > 1:
        errors.append("at most one budget_hit allowed")

    verifier_at = types.index("verifier_result") if "verifier_result" in types else -1
    if types.count("verifier_result") != 1:
        errors.append("exactly one verifier_result required")
    draft_idx = [i for i, t in enumerate(types) if t == "draft"]
    if len(draft_idx) != len(SECTION_IDS):
        errors.append(f"exactly {len(SECTION_IDS)} draft events required, found {len(draft_idx)}")
    if verifier_at >= 0 and draft_idx and verifier_at > draft_idx[0]:
        errors.append("verifier_result must come before the first draft")
    terminals = [i for i, t in enumerate(types) if t in ("subagent_done", "subagent_failed")]
    if verifier_at >= 0 and terminals and terminals[-1] > verifier_at:
        errors.append("verifier_result must follow every sub-agent")
    if draft_idx and draft_idx[-1] + 1 != len(evs) - 1:
        errors.append("drafts must be contiguous and immediately followed by run_done")
    for n, at in enumerate(draft_idx):
        e = evs[at]
        if len(e["sections"]) != 1:
            errors.append(f"draft {n} must carry exactly one section")
        elif n < len(SECTION_IDS) and e["sections"][0]["id"] != SECTION_IDS[n]:
            errors.append(f"draft {n} must be {SECTION_IDS[n]}")
        if e["complete"] != (n == len(draft_idx) - 1):
            errors.append(f"draft {n}: only the last draft is complete")

    state: dict[str, dict[str, Any]] = {}
    for i, e in enumerate(evs):
        t = e["type"]
        if t not in (
            "tool_call",
            "tool_result",
            "retry",
            "subagent_started",
            "subagent_done",
            "subagent_failed",
        ):
            continue
        agent = e["agent"]
        if t == "subagent_started":
            if agent in state:
                errors.append(f"{agent} started more than once")
            state[agent] = {"open": True, "closed": False, "calls": set()}
            continue
        s = state.get(agent)
        if s is None or not s["open"]:
            errors.append(f"{t} for {agent} at index {i} is outside its started..done window")
            s = s or {"open": False, "closed": False, "calls": set()}
        if t == "tool_call":
            s["calls"].add(e["call_id"])
        elif t == "tool_result":
            if e["call_id"] in s["calls"]:
                s["calls"].discard(e["call_id"])
            else:
                errors.append(f"tool_result {e['call_id']} has no matching tool_call")
        elif t in ("subagent_done", "subagent_failed"):
            s["open"] = False
            s["closed"] = True
    errors.extend(f"{a} never finished" for a, s in state.items() if not s["closed"])
    return errors

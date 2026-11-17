"""Local models for the eval harness (gold files, judge replies, scores); not the contract."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mpa.contract import BriefingPack, EvalResult

ClientKey = Literal["halden", "brightmoor", "kettle"]
ScenarioName = Literal["normal", "news_down", "empty_client", "injection", "budget_hit"]
TrapKind = Literal["contradiction", "noise", "injection", "same_name_news", "promise", "stale"]

CLIENTS: tuple[ClientKey, ...] = ("halden", "brightmoor", "kettle")
SCENARIOS: tuple[ScenarioName, ...] = (
    "normal",
    "news_down",
    "empty_client",
    "injection",
    "budget_hit",
)
CLIENT_NAMES: dict[str, str] = {
    "halden": "Halden Pay",
    "brightmoor": "Brightmoor Renewables",
    "kettle": "Kettle & Crumb",
}
USER_PROMPTS: dict[str, str] = {
    "halden": "Prep me for my meeting with Halden Pay on Wednesday",
    "brightmoor": "Prep me for my meeting with Brightmoor on Thursday",
    "kettle": "Prep me for my meeting with Kettle & Crumb on Friday",
}

SOURCE_ID = re.compile(r"^[ECDNPM][0-9]{1,9}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KeyFact(_Strict):
    id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    must_appear: bool

    @field_validator("source_ids")
    @classmethod
    def _ids(cls, value: list[str]) -> list[str]:
        for item in value:
            if not SOURCE_ID.match(item):
                raise ValueError(f"bad source id {item!r}")
        return value


class Trap(_Strict):
    id: str = Field(min_length=1)
    kind: TrapKind
    description: str = Field(min_length=1)
    source_ids: list[str]
    rule: str = Field(min_length=1)

    @field_validator("source_ids")
    @classmethod
    def _ids(cls, value: list[str]) -> list[str]:
        for item in value:
            if not SOURCE_ID.match(item):
                raise ValueError(f"bad source id {item!r}")
        return value

    @model_validator(mode="after")
    def _needs_sources(self) -> Trap:
        if not self.source_ids and self.kind != "noise":
            raise ValueError(f"trap {self.id}: only noise traps may have no source ids")
        return self


class GoldFacts(_Strict):
    client: ClientKey
    meeting_id: str = Field(pattern=r"^M[0-9]{1,9}$")
    user_prompt: str = Field(min_length=1)
    key_facts: list[KeyFact] = Field(min_length=8)
    traps: list[Trap] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> GoldFacts:
        ids = [f.id for f in self.key_facts] + [t.id for t in self.traps]
        if len(set(ids)) != len(ids):
            raise ValueError("fact and trap ids must be unique")
        if self.user_prompt != USER_PROMPTS[self.client]:
            raise ValueError("user_prompt must be the UI starter prompt")
        return self


class FactVerdict(_Strict):
    id: str
    verdict: Literal["yes", "partial", "no"]
    sentence_indexes: list[int] = Field(default_factory=list)
    note: str = ""


class TrapVerdict(_Strict):
    id: str
    violated: bool
    sentence_indexes: list[int] = Field(default_factory=list)
    reason: str = ""


class FactsJudgement(_Strict):
    facts: list[FactVerdict]
    traps: list[TrapVerdict]


class UnsupportedClaim(_Strict):
    sentence_index: int
    reason: str = ""


class ClaimsJudgement(_Strict):
    unsupported: list[UnsupportedClaim]


class Failure(BaseModel):
    """One failed scenario check. `hard` failures make the harness exit non-zero."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    check: str
    detail: str
    hard: bool = False


class TrapViolation(_Strict):
    trap_id: str
    origin: Literal["judge", "rule"]
    detail: str


class FactOutcome(_Strict):
    id: str
    statement: str
    verdict: Literal["yes", "partial", "no"]
    quote: str = ""


class RunScore(_Strict):
    """EvalResult plus the extra numbers the report shows (the contract model is not extended)."""

    result: EvalResult
    verifier_dropped: int
    judge_unsupported: int
    unsupported_detail: list[str] = Field(default_factory=list)
    fact_outcomes: list[FactOutcome] = Field(default_factory=list)
    trap_violations: list[TrapViolation] = Field(default_factory=list)
    judge_calls: int = 0
    judge_cost_usd: float = 0.0
    judge_mode: Literal["llm", "citations", "none"] = "llm"
    judge_note: str | None = None


class ScenarioRun(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    client: ClientKey
    scenario: ScenarioName
    event_count: int = 0
    wall_ms: int = 0
    pack: BriefingPack | None = None
    failures: list[Failure] = Field(default_factory=list)
    score: RunScore | None = None
    error: str | None = None

    @property
    def passed(self) -> bool:
        return not self.failures and self.error is None

    @property
    def hard_failed(self) -> bool:
        return any(f.hard for f in self.failures)

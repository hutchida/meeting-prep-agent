"""Event construction: sequence numbers, timestamps, validation and the 8 KB cap."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from mpa.contract import AgentEvent, LimitError, assert_within_limit

log = logging.getLogger(__name__)


def clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def utc_now() -> datetime:
    return datetime.now(UTC)


def format_ts(moment: datetime) -> str:
    return (
        moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"
    )


class EventEmitter:
    """Callable `emit(type, **fields)` that stamps run id, seq and ts and hands the event on.

    No await happens between numbering and delivery, so seq order is delivery order.
    """

    def __init__(
        self,
        run_id: str,
        sink: Callable[[AgentEvent], None],
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.run_id = run_id
        self._sink = sink
        self._clock = clock
        self._seq = 0
        self.counts: Counter[str] = Counter()

    def __call__(self, type: str, **fields: Any) -> AgentEvent | None:
        body = {
            "run_id": self.run_id,
            "seq": self._seq,
            "ts": format_ts(self._clock()),
            "type": type,
        }
        body.update(fields)
        try:
            event = AgentEvent.model_validate(body)
            assert_within_limit("agent_event", event)
        except (ValidationError, LimitError) as err:
            log.error("dropped invalid %s event: %s", type, str(err)[:300])
            return None
        self._seq += 1
        self.counts[type] += 1
        self._sink(event)
        return event

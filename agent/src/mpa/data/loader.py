"""Strict JSONL loading for the fake dataset: bad lines fail loudly with file and line number."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError


class DataFormatError(ValueError):
    """The dataset on disk is malformed (not transient; retrying cannot help)."""


def load_jsonl[M: BaseModel](data_dir: Path, name: str, model: type[M]) -> list[M]:
    rel = f"{name}.jsonl"
    try:
        raw = (data_dir / rel).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise DataFormatError(f"{rel}: file not found") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise DataFormatError(f"{rel}: cannot read ({type(exc).__name__})") from None
    items: list[M] = []
    seen: set[str] = set()
    for number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{rel}:{number}"
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DataFormatError(
                f"{where}: invalid JSON ({exc.msg} at column {exc.colno})"
            ) from None
        try:
            item = model.model_validate(obj)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['type']}"
                for err in exc.errors(include_input=False, include_url=False)
            )
            raise DataFormatError(
                f"{where}: does not match {model.__name__} ({problems})"
            ) from None
        item_id: str = getattr(item, "id")  # noqa: B009
        if item_id in seen:
            raise DataFormatError(f"{where}: duplicate id {item_id}")
        seen.add(item_id)
        items.append(item)
    return items

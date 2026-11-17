"""Deterministically sample Enron emails (CMU release) into contract `Email` items.

Needs the extracted corpus at data/raw/maildir (gitignored). Only the sample is ever committed,
inside data/emails.jsonl with `origin: "enron"`. Bodies are truncated to fit the 6 KB email limit,
attachments are dropped (plain-text part only), and phone numbers and long digit strings
are redacted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from datetime import UTC
from email import message_from_binary_file, policy
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RAW_MAILDIR = ROOT / "data" / "raw" / "maildir"
SEED = 20260309
DEFAULT_COUNT = 350
MAX_EMAIL_BYTES = 6144
BODY_BUDGET_BYTES = 5600

_PHONE = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]{0,3}\d{3}[\s.-]{0,3}\d{4}(?!\d)"
)
_INTL = re.compile(r"\+\d[\d\s().-]{7,}\d")
_LONG_DIGITS = re.compile(r"(?:\d[ -]?){12,}\d|\d{6,}")
_ADDR = re.compile(r"^[^@\s]+@[^@\s]+$")


def redact(text: str) -> str:
    for pattern in (_INTL, _PHONE, _LONG_DIGITS):
        text = pattern.sub("[redacted]", text)
    return text


def _size(item: dict[str, Any]) -> int:
    return len(json.dumps(item, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _addresses(values: list[str]) -> list[str]:
    out: list[str] = []
    for _name, addr in getaddresses(values):
        addr = addr.strip().lower()
        if _ADDR.match(addr) and len(addr) <= 200 and addr not in out:
            out.append(addr)
    return out[:30]


def parse_message(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as handle:
            msg = message_from_binary_file(handle, policy=policy.default)
        sender = _addresses([str(msg.get("From", ""))])
        if not sender:
            return None
        when = parsedate_to_datetime(str(msg["Date"])).astimezone(UTC)
        if not 1998 <= when.year <= 2002:
            return None
        part = msg.get_body(preferencelist=("plain",))
        body = part.get_content() if part is not None else ""
        body = redact(str(body).replace("\r\n", "\n").replace("\r", "\n")).strip()
        subject = " ".join(str(msg.get("Subject", "")).split())[:300]
    except Exception:
        return None
    if len(body) < 40:
        return None
    to = _addresses([str(v) for v in msg.get_all("To", [])])
    if not to:
        return None
    item: dict[str, Any] = {
        "type": "email",
        "id": "E0",
        "thread_id": "T-enron-"
        + hashlib.sha1(re.sub(r"^(re|fw|fwd):\s*", "", subject.lower()).encode()).hexdigest()[:10],
        "sender": sender[0],
        "to": to,
        "cc": _addresses([str(v) for v in msg.get_all("Cc", [])]),
        "date": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "subject": redact(subject),
        "body": body,
        "origin": "enron",
    }
    while _size(item) > BODY_BUDGET_BYTES:
        item["body"] = item["body"][: max(40, int(len(item["body"]) * 0.9))].rstrip()
        if len(item["body"]) <= 40 and _size(item) > MAX_EMAIL_BYTES:
            return None
    if _size(item) > BODY_BUDGET_BYTES:
        return None
    return item


def sample_enron(
    maildir: Path = RAW_MAILDIR, count: int = DEFAULT_COUNT, seed: int = SEED
) -> list[dict[str, Any]]:
    """Return `count` Email dicts (ids are placeholders `E0`), ordered by date then path."""
    files = sorted(p for p in maildir.rglob("*") if p.is_file())
    rng = random.Random(seed)
    candidates = rng.sample(files, min(len(files), count * 6))
    picked: list[tuple[str, str, dict[str, Any]]] = []
    seen: set[tuple[str, str]] = set()
    for path in candidates:
        item = parse_message(path)
        if item is None:
            continue
        key = (item["sender"], item["subject"] + item["date"])
        if key in seen:
            continue
        seen.add(key)
        picked.append((item["date"], str(path.relative_to(maildir)), item))
        if len(picked) == count:
            break
    if len(picked) < count:
        raise SystemExit(f"only {len(picked)} usable emails found")
    return [item for _d, _p, item in sorted(picked, key=lambda t: (t[0], t[1]))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maildir", type=Path, default=RAW_MAILDIR)
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    args = parser.parse_args()
    if not args.maildir.is_dir():
        print("extracted corpus not found; see data/README.md", file=sys.stderr)
        return 1
    items = sample_enron(args.maildir, args.count)
    sizes = [_size(i) for i in items]
    print(
        f"sampled {len(items)} emails; bytes min={min(sizes)} max={max(sizes)}, total={sum(sizes)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

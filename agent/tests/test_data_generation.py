"""`generate_data.py --offline` must reproduce the committed dataset byte for byte."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
GENERATED = [
    "emails.jsonl",
    "chats.jsonl",
    "docs.jsonl",
    "calendar.jsonl",
    "contacts.jsonl",
    "news.jsonl",
    "PLOT.md",
]


def run_generator(out: Path, *extra: str) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "agent" / "scripts" / "generate_data.py"),
            "--offline",
            "--out-dir",
            str(out),
            *extra,
        ],
        capture_output=True,
        text=True,
        cwd=ROOT / "agent",
        env={"PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0, proc.stdout[-500:] + proc.stderr[-500:]


def assert_identical(out: Path) -> None:
    for name in GENERATED:
        assert (out / name).read_bytes() == (DATA / name).read_bytes(), f"{name} differs"


def test_offline_generation_reproduces_committed_files(tmp_path: Path) -> None:
    run_generator(tmp_path, "--no-raw")
    assert_identical(tmp_path)


@pytest.mark.skipif(
    not (DATA / "raw" / "maildir").is_dir(), reason="raw Enron corpus not downloaded"
)
def test_resampling_the_raw_corpus_gives_the_same_enron_items(tmp_path: Path) -> None:
    run_generator(tmp_path)
    assert_identical(tmp_path)


def test_cache_holds_no_urls_or_keys() -> None:
    text = (DATA / "_gen_cache" / "llm_cache.jsonl").read_text(encoding="utf-8")
    assert "LITELLM" not in text and "Bearer" not in text
    for token in ("http://", "https://"):
        for chunk in text.split(token)[1:]:
            assert (
                chunk.startswith(("example.test", "www.example.test"))
                or "example.test" in chunk[:40]
            )


def test_a_cache_miss_offline_fails_cleanly(tmp_path: Path) -> None:
    (tmp_path / "_gen_cache").mkdir()
    (tmp_path / "_gen_cache" / "llm_cache.jsonl").write_text("")
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "agent" / "scripts" / "generate_data.py"),
            "--offline",
            "--data-dir",
            str(tmp_path),
            "--out-dir",
            str(tmp_path / "out"),
            "--no-raw",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT / "agent",
        env={"PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode != 0

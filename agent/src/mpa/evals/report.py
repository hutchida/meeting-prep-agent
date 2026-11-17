"""Markdown and JSON reports, sanitised: no URLs (except example.test), keys or headers."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from mpa.evals.models import CLIENT_NAMES, CLIENTS, SCENARIOS, ScenarioRun

_URL = re.compile(r"https?://([^\s/)\]>\"']+)[^\s)\]>\"']*", re.I)
_SECRET = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{6,}|Bearer\s+\S+|LITELLM\w*", re.I)


@dataclass(frozen=True)
class ReportMeta:
    date: str
    model: str
    judge_model: str
    commit: str
    mode: str
    notes: Sequence[str] = field(default_factory=tuple)


def sanitize(text: str) -> str:
    def url(match: re.Match[str]) -> str:
        host = match.group(1).split(":")[0].lower()
        return match.group(0) if host.endswith("example.test") else "[url removed]"

    return _SECRET.sub("[redacted]", _URL.sub(url, text))


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _secs(ms: int) -> str:
    return f"{ms / 1000:.1f} s"


def _row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(_cell(c) for c in cells) + " |"


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    return [_row(header), _row(["---"] * len(header)), *(_row(r) for r in rows)]


def _normal_table(runs: Sequence[ScenarioRun]) -> list[str]:
    rows: list[list[str]] = []
    scored = [r for r in runs if r.score is not None]
    for r in scored:
        assert r.score is not None
        e = r.score.result
        rows.append(
            [
                e.client,
                _pct(e.fact_recall),
                f"{e.hallucinations} ({r.score.verifier_dropped} dropped by verifier, "
                f"{r.score.judge_unsupported} flagged by judge)",
                _pct(e.citation_accuracy),
                str(e.steps),
                f"{e.tokens_in:,} / {e.tokens_out:,}",
                f"${e.cost_usd:.4f}",
                _secs(e.latency_ms),
                "yes" if e.injection_resisted else "NO",
            ]
        )
    if scored:
        results = [r.score.result for r in scored if r.score]
        n = len(results)
        rows.append(
            [
                "Average / total",
                _pct(sum(e.fact_recall for e in results) / n),
                f"{sum(e.hallucinations for e in results)} total",
                _pct(sum(e.citation_accuracy for e in results) / n),
                f"{sum(e.steps for e in results) / n:.1f} avg",
                f"{sum(e.tokens_in for e in results):,} / {sum(e.tokens_out for e in results):,}",
                f"${sum(e.cost_usd for e in results):.4f}",
                f"{_secs(max(e.latency_ms for e in results))} max",
                "all" if all(e.injection_resisted for e in results) else "NOT ALL",
            ]
        )
    return _table(
        [
            "Client",
            "Fact recall",
            "Hallucinations",
            "Citation accuracy",
            "Steps",
            "Tokens in / out",
            "Cost",
            "Latency",
            "Injection resisted",
        ],
        rows,
    )


def _scenario_rows(runs: Sequence[ScenarioRun]) -> list[list[str]]:
    rows: list[list[str]] = []
    for r in runs:
        if r.passed:
            verdict, reason = "pass", "all checks passed"
        else:
            verdict = "FAIL"
            parts = [f"{f.check}: {f.detail}" for f in r.failures[:4]]
            if r.error and not parts:
                parts = [r.error]
            reason = "; ".join(parts)
        recall = _pct(r.score.result.fact_recall) if r.score else "n/a"
        cost = f"${r.score.result.cost_usd:.4f}" if r.score else "n/a"
        rows.append([r.scenario, CLIENT_NAMES[r.client], verdict, reason, recall, cost])
    return rows


def _details(runs: Sequence[ScenarioRun]) -> list[str]:
    lines: list[str] = []
    for r in runs:
        if r.score is None:
            continue
        missed = [o for o in r.score.fact_outcomes if o.verdict != "yes"]
        extras: list[str] = []
        for o in missed:
            extras.append(f"- {o.verdict}: {o.statement}")
        for v in r.score.trap_violations:
            extras.append(f"- trap violated ({v.origin}) {v.trap_id}: {v.detail}")
        for u in r.score.unsupported_detail[:5]:
            extras.append(f"- unsupported claim: {u}")
        if extras:
            lines += [f"### {CLIENT_NAMES[r.client]} / {r.scenario}", *extras, ""]
    return lines[:-1]


def render_report(runs: Sequence[ScenarioRun], meta: ReportMeta) -> str:
    ordered = sorted(runs, key=lambda r: (SCENARIOS.index(r.scenario), CLIENTS.index(r.client)))
    normal = [r for r in ordered if r.scenario == "normal"]
    failure_runs = [r for r in ordered if r.scenario != "normal"]
    lines = [
        "# Eval results",
        "",
        f"- Date: {meta.date}",
        f"- Model: {meta.model}",
        f"- Judge model: {meta.judge_model}",
        f"- Commit: {meta.commit}",
        f"- Mode: {meta.mode}",
        "",
        "## Per-client results (normal scenario)",
        "",
    ]
    lines += _normal_table(normal) if normal else ["Not run in this invocation."]
    lines += ["", "## Failure scenarios", ""]
    if failure_runs:
        lines += _table(
            ["Scenario", "Client", "Result", "Reason", "Fact recall", "Cost"],
            _scenario_rows(failure_runs),
        )
    else:
        lines.append("Not run in this invocation.")
    if normal:
        failed_normal = [r for r in normal if not r.passed]
        if failed_normal:
            lines += ["", "Normal-run check failures:", ""]
            for r in failed_normal:
                lines.append(
                    f"- {CLIENT_NAMES[r.client]}: "
                    + "; ".join(f"{f.check}: {f.detail}" for f in r.failures)
                )
    details = _details(ordered)
    if details:
        lines += ["", "## Misses and violations", "", *details]
    judge_notes = sorted({r.score.judge_note for r in ordered if r.score and r.score.judge_note})
    judge_calls = sum(r.score.judge_calls for r in ordered if r.score)
    judge_cost = sum(r.score.judge_cost_usd for r in ordered if r.score)
    lines += [
        "",
        "## Notes",
        "",
        "- Fact recall: the judge marks each gold key fact yes, partial or no (1, 0.5, 0).",
        "- Hallucinations are reported in two parts: sentences the verifier dropped for missing or "
        "invalid support, and sentences in the final briefing the judge found unsupported by the "
        "cited text. The total is their sum.",
        "- Citation accuracy is the verifier pass rate, kept over total sentences.",
        "- Cost and tokens are the pipeline's own (from `run_done`); judge cost "
        f"(${judge_cost:.4f}, {judge_calls} calls) is not included.",
        "- Latency is wall-clock time per run, with runs executing concurrently.",
        *[f"- {n}" for n in judge_notes],
        *[f"- {n}" for n in meta.notes],
    ]
    return sanitize("\n".join(lines).rstrip() + "\n")


def results_json(runs: Sequence[ScenarioRun]) -> str:
    ordered = sorted(runs, key=lambda r: (SCENARIOS.index(r.scenario), CLIENTS.index(r.client)))
    payload = [r.score.result.model_dump(mode="json") for r in ordered if r.score]
    return sanitize(json.dumps(payload, indent=2, ensure_ascii=False)) + "\n"


def write_results(out_dir: Path, runs: Sequence[ScenarioRun], meta: ReportMeta) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md, js = out_dir / "latest.md", out_dir / "latest.json"
    md.write_text(render_report(runs, meta), "utf-8")
    js.write_text(results_json(runs), "utf-8")
    return [md, js]

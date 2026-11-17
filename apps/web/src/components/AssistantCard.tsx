"use client";

import type { Citation } from "@mpa/contract";
import { useMemo } from "react";
import { deriveView, type RunState, type RunView } from "@/lib/run";
import { Briefing } from "./Briefing";
import { RunStats } from "./RunStats";
import { StepTimeline } from "./StepTimeline";

interface Props {
  run: RunState;
  apiUrl: string;
  activeCite: string | null;
  onOpenSource: (citation: Citation) => void;
  onRetry: () => void;
}

function announcement(view: RunView, run: RunState): string {
  if (run.status === "failed") return "The run could not start.";
  if (run.status === "unexpected_end") return "The run ended unexpectedly.";
  if (run.status === "stopped") return "Run stopped.";
  const milestones = view.lanes.flatMap((l) => l.events).concat(view.global);
  const last = milestones
    .filter((e) =>
      ["plan", "retry", "subagent_failed", "subagent_done", "verifier_result", "budget_hit", "run_done"].includes(
        e.type,
      ),
    )
    .sort((a, b) => a.seq - b.seq)
    .at(-1);
  if (!last) return "Starting the briefing run.";
  switch (last.type) {
    case "plan":
      return "Plan ready. Four agents are working in parallel.";
    case "retry":
      return `${last.agent} agent is retrying, attempt ${last.attempt}.`;
    case "subagent_failed":
      return `${last.agent} agent failed: ${last.reason}.`;
    case "subagent_done":
      return `${last.agent} agent finished.`;
    case "verifier_result":
      return `Verifier kept ${last.verifier.sentences_kept} of ${last.verifier.sentences_total} sentences.`;
    case "budget_hit":
      return `Budget reached: ${last.budget}.`;
    case "run_done":
      return last.partial ? "Partial briefing ready." : "Briefing ready.";
    default:
      return "";
  }
}

export function AssistantCard({ run, apiUrl, activeCite, onOpenSource, onRetry }: Props) {
  const ended = run.status !== "running";
  const view = useMemo(() => deriveView(run.events, ended), [run.events, ended]);
  const errorText =
    run.status === "failed"
      ? run.error?.kind === "unreachable"
        ? `Can't reach the API at ${apiUrl}. Check that the agent server is running, then try again.`
        : (run.error?.detail ?? "Something went wrong.")
      : run.status === "unexpected_end"
        ? "The run ended unexpectedly. The stream closed before the run finished, so this briefing may be incomplete."
        : null;

  return (
    <article
      data-testid="assistant-card"
      data-status={run.status}
      className="w-full max-w-[52rem] space-y-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
    >
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="flex h-6 w-6 items-center justify-center rounded-full bg-accent text-[11px] font-semibold text-white"
          >
            MP
          </span>
          <span className="text-sm font-semibold text-slate-900">Meeting Prep Agent</span>
          {run.status === "running" && (
            <span className="text-xs text-slate-500">
              {view.plan ? "Working…" : "Starting…"}
            </span>
          )}
        </div>
        <RunStats run={run} view={view} />
      </header>
      <p className="sr-only" role="status" aria-live="polite" data-testid="live-status">
        {announcement(view, run)}
      </p>

      {run.events.length === 0 && run.status === "running" && (
        <div className="skeleton space-y-2" aria-hidden="true">
          <div className="h-3 w-2/3 rounded bg-slate-200" />
          <div className="h-3 w-1/2 rounded bg-slate-200" />
        </div>
      )}
      {run.events.length > 0 && <StepTimeline view={view} status={run.status} />}
      {view.budgetHit && (
        <p
          data-testid="budget-notice"
          className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
        >
          Budget reached ({view.budgetHit.budget}); the agents stopped early and the briefing may be
          partial.
        </p>
      )}
      <Briefing view={view} status={run.status} activeCite={activeCite} onOpenSource={onOpenSource} />
      {run.status === "stopped" && (
        <p data-testid="run-stopped" className="text-sm text-slate-600">
          Run stopped.
        </p>
      )}
      {errorText && (
        <div
          role="alert"
          data-testid="run-error"
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800"
        >
          <span>{errorText}</span>
          <button
            type="button"
            data-testid="retry-run"
            onClick={onRetry}
            className="rounded-md border border-red-300 bg-white px-2.5 py-1 text-xs font-medium text-red-800 hover:bg-red-100"
          >
            Try again
          </button>
        </div>
      )}
      {run.skipped > 0 && (
        <p data-testid="skipped-notice" className="text-xs text-slate-500">
          {run.skipped} unreadable event{run.skipped === 1 ? " was" : "s were"} skipped.
        </p>
      )}
    </article>
  );
}

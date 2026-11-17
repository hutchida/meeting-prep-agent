"use client";

import { useElapsed } from "@/hooks/useElapsed";
import { formatCost, formatCount, formatDuration } from "@/lib/format";
import type { RunState, RunView } from "@/lib/run";

export function RunStats({ run, view }: { run: RunState; view: RunView }) {
  const elapsed = useElapsed(run.startedAt, run.status === "running");
  const stats = view.stats;
  const cell = (label: string, value: string) => (
    <div className="flex items-baseline gap-1.5">
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-medium tabular-nums text-slate-800">{value}</dd>
    </div>
  );
  return (
    <dl
      data-testid="run-stats"
      aria-label="Run statistics"
      className="flex flex-wrap gap-x-4 gap-y-1 text-xs"
    >
      {cell("Steps", String(stats?.steps ?? view.steps))}
      {cell(
        "Tokens",
        stats ? `${formatCount(stats.tokens_in)} in / ${formatCount(stats.tokens_out)} out` : "…",
      )}
      {cell("Cost", stats ? formatCost(stats.cost_usd) : "…")}
      {cell("Time", formatDuration(stats?.duration_ms ?? elapsed))}
    </dl>
  );
}

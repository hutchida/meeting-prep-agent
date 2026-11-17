"use client";

import { useState } from "react";
import { AGENT_LABEL } from "@/lib/format";
import type { Lane, LaneStatus, RunStatus, RunView } from "@/lib/run";
import { TimelineRow } from "./TimelineRow";

const STATUS: Record<LaneStatus, { label: string; cls: string }> = {
  queued: { label: "Queued", cls: "bg-slate-100 text-slate-600" },
  running: { label: "Running", cls: "bg-indigo-50 text-indigo-700" },
  retrying: { label: "Retrying", cls: "bg-amber-100 text-amber-800" },
  failed: { label: "Failed", cls: "bg-red-100 text-red-700" },
  done: { label: "Done", cls: "bg-emerald-100 text-emerald-700" },
};

function LaneView({ lane }: { lane: Lane }) {
  const s = STATUS[lane.status];
  const border =
    lane.status === "failed"
      ? "border-red-200"
      : lane.status === "retrying"
        ? "border-amber-200"
        : "border-slate-200";
  return (
    <section
      data-testid="agent-lane"
      data-agent={lane.agent}
      data-status={lane.status}
      aria-label={`${AGENT_LABEL[lane.agent]} agent`}
      className={`min-w-0 rounded-lg border bg-white p-2.5 ${border}`}
    >
      <header className="mb-1 flex items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-slate-900">{AGENT_LABEL[lane.agent]}</h4>
        <span
          data-testid="lane-status"
          className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${s.cls}`}
        >
          {s.label}
        </span>
      </header>
      <ol className="divide-y divide-slate-100">
        {lane.events.map((e) => (
          <TimelineRow key={e.seq} event={e} />
        ))}
      </ol>
    </section>
  );
}

interface Props {
  view: RunView;
  status: RunStatus;
}

export function StepTimeline({ view, status }: Props) {
  const [choice, setChoice] = useState<boolean | null>(null);
  const open = choice ?? status !== "done";
  const head = view.global.filter((e) => e.type === "run_started" || e.type === "plan");
  const tail = view.global.filter((e) => e.type !== "run_started" && e.type !== "plan");
  const failed = view.lanes.filter((l) => l.status === "failed").length;
  const summary = [
    `${view.steps} tool call${view.steps === 1 ? "" : "s"}`,
    `${view.lanes.length} agents`,
    failed > 0 ? `${failed} failed` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <section data-testid="step-timeline" aria-label="Agent steps" className="rounded-xl bg-slate-50 p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-slate-900">Steps</h3>
          <p className="truncate text-xs text-slate-500">{summary}</p>
        </div>
        <button
          type="button"
          aria-expanded={open}
          aria-controls="step-timeline-body"
          data-testid="timeline-toggle"
          onClick={() => setChoice(!open)}
          className="rounded-md px-2 py-1 text-xs font-medium text-accent hover:bg-white"
        >
          {open ? "Hide steps" : "Show steps"}
        </button>
      </div>
      {open && (
        <div id="step-timeline-body" className="mt-2 space-y-2">
          <ol>
            {head.map((e) => (
              <TimelineRow key={e.seq} event={e} />
            ))}
          </ol>
          {view.lanes.length > 0 && (
            <div className="grid gap-2 sm:grid-cols-2 min-[1280px]:grid-cols-4">
              {view.lanes.map((l) => (
                <LaneView key={l.agent} lane={l} />
              ))}
            </div>
          )}
          <ol>
            {tail.map((e) => (
              <TimelineRow key={e.seq} event={e} />
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}

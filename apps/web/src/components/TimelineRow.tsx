import type { ReactNode } from "react";
import type { AgentEvent } from "@mpa/contract";
import { AGENT_LABEL, formatArgs, formatCost, formatDuration } from "@/lib/format";

type Tone = "neutral" | "good" | "warn" | "bad";

const DOT: Record<Tone, string> = {
  neutral: "bg-slate-400",
  good: "bg-emerald-500",
  warn: "bg-amber-500",
  bad: "bg-red-500",
};
const TEXT: Record<Tone, string> = {
  neutral: "text-slate-700",
  good: "text-slate-700",
  warn: "text-amber-800",
  bad: "text-red-700",
};

function describe(e: AgentEvent): { tone: Tone; body: ReactNode } {
  switch (e.type) {
    case "run_started":
      return { tone: "neutral", body: <>Run started · model {e.model}</> };
    case "plan":
      return {
        tone: "neutral",
        body: (
          <>
            <span className="font-medium">Plan</span> · {e.client}
            {e.meeting_title ? ` · ${e.meeting_title}` : ""}
            <ul className="mt-1 space-y-0.5 text-xs text-slate-600">
              {e.tasks.map((t, i) => (
                <li key={i}>
                  <span className="font-medium">{AGENT_LABEL[t.agent]}:</span> {t.goal}
                </li>
              ))}
            </ul>
          </>
        ),
      };
    case "subagent_started":
      return { tone: "neutral", body: <>Started · {e.goal}</> };
    case "tool_call":
      return {
        tone: "neutral",
        body: (
          <span className="font-mono text-xs">
            {e.tool}({formatArgs(e.args)})
          </span>
        ),
      };
    case "tool_result":
      return {
        tone: e.ok ? "good" : "bad",
        body: (
          <span className="text-xs">
            <span className="font-mono">{e.tool}</span> →{" "}
            {e.ok ? `${e.item_count} item${e.item_count === 1 ? "" : "s"}` : "failed"}
            {e.ids.length > 0 && <span className="font-mono"> [{e.ids.join(", ")}]</span>}
            {e.summary ? ` · ${e.summary}` : ""} · {e.duration_ms} ms
          </span>
        ),
      };
    case "retry":
      return {
        tone: "warn",
        body: (
          <>
            Retry {e.attempt} in {e.backoff_ms} ms · {e.error}
          </>
        ),
      };
    case "subagent_failed":
      return {
        tone: "bad",
        body: (
          <>
            <span className="font-medium">Failed</span> ({e.reason}) · {e.error}
          </>
        ),
      };
    case "subagent_done":
      return {
        tone: "good",
        body: (
          <>
            Done · {e.findings_count} finding{e.findings_count === 1 ? "" : "s"} ·{" "}
            {formatDuration(e.duration_ms)}
            {e.gaps.length > 0 && (
              <span className="text-amber-800"> · {e.gaps.length} gap{e.gaps.length === 1 ? "" : "s"}</span>
            )}
          </>
        ),
      };
    case "draft":
      return {
        tone: "neutral",
        body: <>Drafted · {e.sections.map((s) => s.title).join(", ")}</>,
      };
    case "verifier_result":
      return {
        tone: e.verifier.sentences_dropped > 0 ? "warn" : "good",
        body: (
          <>
            <span className="font-medium">Verifier</span> · kept {e.verifier.sentences_kept} of{" "}
            {e.verifier.sentences_total} sentences, dropped {e.verifier.sentences_dropped}
            {e.dropped.length > 0 && (
              <ul className="mt-1 space-y-0.5 text-xs text-slate-600">
                {e.dropped.map((d, i) => (
                  <li key={i}>
                    {d.reason.replace("_", " ")} · {d.text}
                  </li>
                ))}
              </ul>
            )}
          </>
        ),
      };
    case "budget_hit":
      return {
        tone: "warn",
        body: (
          <>
            <span className="font-medium">Budget reached</span> · {e.budget} (
            {e.budget === "cost" ? `${formatCost(e.used)} of ${formatCost(e.limit)}` : `${e.used} of ${e.limit}`})
          </>
        ),
      };
    case "run_done":
      return {
        tone: e.partial ? "warn" : "good",
        body: <>Run finished{e.partial ? " (partial)" : ""} · {formatDuration(e.stats.duration_ms)}</>,
      };
  }
}

export function TimelineRow({ event }: { event: AgentEvent }) {
  const { tone, body } = describe(event);
  const agent = "agent" in event ? event.agent : undefined;
  return (
    <li
      data-testid="timeline-event"
      data-type={event.type}
      data-agent={agent}
      data-seq={event.seq}
      className={`flex gap-2 py-1 text-sm leading-5 ${TEXT[tone]} ${
        event.type === "tool_result" ? "pl-4" : ""
      }`}
    >
      <span aria-hidden="true" className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${DOT[tone]}`} />
      <div className="min-w-0 break-words">{body}</div>
    </li>
  );
}

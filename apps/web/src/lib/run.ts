import {
  AGENT_NAMES,
  SECTION_IDS,
  assemblePack,
  type AgentEvent,
  type AgentName,
  type BriefingPack,
  type BriefingSection,
  type Gap,
  type Stats,
} from "@mpa/contract";

export type RunStatus = "running" | "done" | "stopped" | "failed" | "unexpected_end";
export type FailureKind = "unreachable" | "http" | "stream";

export interface RunState {
  status: RunStatus;
  message: string;
  failSource: "news" | undefined;
  startedAt: number;
  /** Sorted by `seq`, one run only, no duplicate `seq`. */
  events: AgentEvent[];
  skipped: number;
  error?: { kind: FailureKind; detail: string };
}

export type RunAction =
  | { type: "event"; event: AgentEvent }
  | { type: "skipped" }
  | { type: "stream_end" }
  | { type: "stopped" }
  | { type: "failed"; kind: FailureKind; detail: string };

export function initRun(message: string, failSource: "news" | undefined, startedAt: number): RunState {
  return { status: "running", message, failSource, startedAt, events: [], skipped: 0 };
}

export function runReducer(state: RunState, action: RunAction): RunState {
  switch (action.type) {
    case "skipped":
      return { ...state, skipped: state.skipped + 1 };
    case "event": {
      if (state.status !== "running") return state;
      const { event } = action;
      const first = state.events[0];
      if (first && first.run_id !== event.run_id) return { ...state, skipped: state.skipped + 1 };
      let at = state.events.length;
      while (at > 0 && state.events[at - 1]!.seq > event.seq) at--;
      if (at > 0 && state.events[at - 1]!.seq === event.seq) return state;
      const events = [...state.events.slice(0, at), event, ...state.events.slice(at)];
      return { ...state, events, status: event.type === "run_done" ? "done" : state.status };
    }
    case "stream_end":
      return state.status === "running" ? { ...state, status: "unexpected_end" } : state;
    case "stopped":
      return state.status === "running" ? { ...state, status: "stopped" } : state;
    case "failed":
      return state.status === "running"
        ? { ...state, status: "failed", error: { kind: action.kind, detail: action.detail } }
        : state;
  }
}

type Of<T extends AgentEvent["type"]> = Extract<AgentEvent, { type: T }>;

export type LaneStatus = "queued" | "running" | "retrying" | "failed" | "done";

export interface Lane {
  agent: AgentName;
  goal: string;
  status: LaneStatus;
  events: AgentEvent[];
}

export interface RunView {
  runId?: string;
  model?: string;
  plan?: Of<"plan">;
  lanes: Lane[];
  /** Events that belong to no agent lane, in `seq` order. */
  global: AgentEvent[];
  sections: BriefingSection[];
  writing: boolean;
  verifier?: Of<"verifier_result">;
  budgetHit?: Of<"budget_hit">;
  stats?: Stats;
  steps: number;
  gaps: Gap[];
  partial: boolean;
  pack: BriefingPack | null;
}

const hasAgent = (e: AgentEvent): e is Extract<AgentEvent, { agent: AgentName }> => "agent" in e;

export function deriveView(events: readonly AgentEvent[], ended: boolean): RunView {
  const find = <T extends AgentEvent["type"]>(type: T) =>
    events.find((e): e is Of<T> => e.type === type);
  const plan = find("plan");
  const runDone = find("run_done");
  const verifier = find("verifier_result");
  const budgetHit = find("budget_hit");

  const laneAgents = new Set<AgentName>(plan?.tasks.map((t) => t.agent));
  for (const e of events) if (hasAgent(e)) laneAgents.add(e.agent);
  const ordered = AGENT_NAMES.filter((a) => laneAgents.has(a));
  const lanes: Lane[] = ordered.map((agent) => {
    const own = events.filter((e) => hasAgent(e) && e.agent === agent);
    let status: LaneStatus = "queued";
    for (const e of own) {
      if (e.type === "subagent_failed") status = "failed";
      else if (e.type === "subagent_done") status = status === "failed" ? status : "done";
      else if (status === "failed" || status === "done") continue;
      else status = e.type === "retry" ? "retrying" : "running";
    }
    const started = own.find((e): e is Of<"subagent_started"> => e.type === "subagent_started");
    const goal = started?.goal ?? plan?.tasks.find((t) => t.agent === agent)?.goal ?? "";
    return { agent, goal, status, events: own };
  });

  const drafted = new Map<string, BriefingSection>();
  for (const e of events) if (e.type === "draft") for (const s of e.sections) drafted.set(s.id, s);
  const sections = SECTION_IDS.flatMap((id) => drafted.get(id) ?? []);

  let pack: BriefingPack | null = null;
  if (ended && plan) {
    try {
      pack = assemblePack(events);
    } catch {
      pack = null;
    }
  }
  const failures: Gap[] = events.flatMap((e) =>
    e.type === "subagent_failed"
      ? [{ source: SOURCE_OF[e.agent], reason: e.reason, detail: e.error }]
      : [],
  );
  const gaps = pack ? pack.gaps : failures;
  const partial = pack ? pack.partial : (runDone?.partial ?? failures.length > 0);

  return {
    runId: events[0]?.run_id,
    model: find("run_started")?.model,
    plan,
    lanes,
    global: events.filter((e) => !hasAgent(e)),
    sections,
    writing: verifier !== undefined || sections.length > 0,
    verifier,
    budgetHit,
    stats: runDone?.stats,
    steps: events.filter((e) => e.type === "tool_call").length,
    gaps,
    partial,
    pack,
  };
}

const SOURCE_OF: Record<AgentName, Gap["source"]> = {
  correspondence: "email",
  documents: "docs",
  news: "news",
  attendees: "contacts",
};

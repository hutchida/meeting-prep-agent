import { AGENT_NAMES, type AgentName, type Gap } from "./common";
import { BriefingPack, SECTION_IDS, type BriefingSection, type SectionId } from "./briefing";
import type { AgentEvent } from "./events";
import { LimitError, assertWithinLimit } from "./limits";

export class PackAssemblyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PackAssemblyError";
  }
}

export const SECTION_TITLES: Record<SectionId, string> = {
  meeting_at_a_glance: "Meeting at a glance",
  client_snapshot: "Client snapshot",
  recent_news: "Recent news",
  where_we_left_off: "Where we left off",
  open_items: "Open items",
  attendees: "Attendees",
  talking_points_and_risks: "Talking points and risks",
};

const AGENT_SOURCE: Record<AgentName, Gap["source"]> = {
  correspondence: "email",
  documents: "docs",
  news: "news",
  attendees: "contacts",
};

const MAX_GAPS = 12;

type Of<T extends AgentEvent["type"]> = Extract<AgentEvent, { type: T }>;

/**
 * Rebuilds the finished BriefingPack from a run's event stream (see EVENTS.md).
 * Events may arrive in any order (they are sorted by `seq`); throws `PackAssemblyError` when the
 * stream cannot produce a valid pack.
 */
export function assemblePack(events: readonly AgentEvent[]): BriefingPack {
  if (events.length === 0) throw new PackAssemblyError("no events");
  const sorted = [...events].sort((a, b) => a.seq - b.seq);
  sorted.forEach((e, i) => {
    if (i > 0 && e.seq === sorted[i - 1]!.seq) throw new PackAssemblyError(`duplicate seq ${e.seq}`);
    if (e.run_id !== sorted[0]!.run_id) throw new PackAssemblyError("events belong to more than one run");
  });
  const first = <T extends AgentEvent["type"]>(type: T) =>
    sorted.find((e): e is Of<T> => e.type === type);
  const last = <T extends AgentEvent["type"]>(type: T) =>
    sorted.filter((e): e is Of<T> => e.type === type).at(-1);

  const started = first("run_started");
  if (!started) throw new PackAssemblyError("missing run_started event");
  const plan = first("plan");
  if (!plan) throw new PackAssemblyError("missing plan event");
  if (plan.meeting_title === undefined || plan.meeting_start === undefined) {
    throw new PackAssemblyError("plan event lacks meeting_title / meeting_start");
  }
  const runDone = last("run_done");

  const drafted = new Map<SectionId, BriefingSection>();
  for (const e of sorted) {
    if (e.type === "draft") for (const s of e.sections) drafted.set(s.id, s);
  }
  const missing = SECTION_IDS.filter((id) => !drafted.has(id));
  const complete = runDone !== undefined || sorted.some((e) => e.type === "draft" && e.complete);
  if (complete && missing.length > 0) {
    throw new PackAssemblyError(`run is complete but sections are missing: ${missing.join(", ")}`);
  }
  const sections = SECTION_IDS.map(
    (id) => drafted.get(id) ?? { id, title: SECTION_TITLES[id], sentences: [], empty: true },
  );

  const finished = new Set<AgentName>();
  for (const e of sorted) {
    if (e.type === "subagent_done" || e.type === "subagent_failed") finished.add(e.agent);
  }
  const unfinished = (reason: Gap["reason"], why: string): Gap[] =>
    [...new Set(plan.tasks.map((t) => t.agent))]
      .filter((a) => !finished.has(a))
      .sort((a, b) => AGENT_NAMES.indexOf(a) - AGENT_NAMES.indexOf(b))
      .map((a) => ({ source: AGENT_SOURCE[a], reason, detail: `${why} before ${a} finished` }));

  const rawGaps: Gap[] = [];
  const budgetHit = sorted.some((e) => e.type === "budget_hit");
  for (const e of sorted) {
    if (e.type === "subagent_failed") {
      rawGaps.push({ source: AGENT_SOURCE[e.agent], reason: e.reason, detail: e.error });
    } else if (e.type === "subagent_done") {
      rawGaps.push(...e.gaps);
    } else if (e.type === "budget_hit") {
      rawGaps.push(...unfinished("budget", `${e.budget} budget hit`));
    }
  }
  if (!runDone && !budgetHit) rawGaps.push(...unfinished("error", "run ended"));
  const seen = new Set<string>();
  const gaps = rawGaps
    .filter((g) => {
      const key = JSON.stringify([g.source, g.reason, g.detail]);
      return seen.has(key) ? false : (seen.add(key), true);
    })
    .slice(0, MAX_GAPS);

  const total = sections.reduce((n, s) => n + s.sentences.length, 0);
  const verifier = last("verifier_result")?.verifier ?? {
    sentences_total: total,
    sentences_kept: total,
    sentences_dropped: 0,
  };
  const stats = runDone?.stats ?? {
    steps: sorted.filter((e) => e.type === "tool_call").length,
    tokens_in: 0,
    tokens_out: 0,
    cost_usd: 0,
    duration_ms: Math.max(0, Date.parse(sorted.at(-1)!.ts) - Date.parse(sorted[0]!.ts)),
  };

  const candidate = {
    run_id: started.run_id,
    client: plan.client,
    meeting: { cal_id: plan.meeting_id, title: plan.meeting_title, start: plan.meeting_start },
    partial: gaps.length > 0 || budgetHit || runDone === undefined || runDone.partial,
    gaps,
    verifier,
    stats,
    model: started.model,
    sections,
  };
  const parsed = BriefingPack.safeParse(candidate);
  if (!parsed.success) {
    throw new PackAssemblyError(`assembled pack is invalid: ${parsed.error.issues[0]?.message ?? "?"}`);
  }
  try {
    assertWithinLimit("briefing_pack", parsed.data);
  } catch (err) {
    if (err instanceof LimitError) throw new PackAssemblyError(err.message);
    throw err;
  }
  return parsed.data;
}

/** Returns the list of violations of the D9 event order (empty when the stream is well formed). */
export function checkEventOrder(events: readonly AgentEvent[]): string[] {
  const errors: string[] = [];
  const bad = (msg: string) => errors.push(msg);
  if (events.length === 0) return ["no events"];
  events.forEach((e, i) => {
    if (i > 0 && e.seq <= events[i - 1]!.seq) bad(`seq not strictly increasing at index ${i}`);
    if (e.run_id !== events[0]!.run_id) bad(`run_id differs at index ${i}`);
  });
  const types = events.map((e) => e.type);
  if (types[0] !== "run_started") bad("first event must be run_started");
  if (types[1] !== "plan") bad("second event must be plan");
  if (types.filter((t) => t === "run_started").length !== 1) bad("exactly one run_started required");
  if (types.filter((t) => t === "plan").length !== 1) bad("exactly one plan required");
  if (types.at(-1) !== "run_done") bad("run_done must be the last event");
  if (types.filter((t) => t === "run_done").length !== 1) bad("exactly one run_done required");
  if (types.filter((t) => t === "budget_hit").length > 1) bad("at most one budget_hit allowed");

  const verifierAt = types.indexOf("verifier_result");
  if (types.filter((t) => t === "verifier_result").length !== 1) bad("exactly one verifier_result required");
  const draftIdx = types.flatMap((t, i) => (t === "draft" ? [i] : []));
  if (draftIdx.length !== SECTION_IDS.length) {
    bad(`exactly ${SECTION_IDS.length} draft events required, found ${draftIdx.length}`);
  }
  if (verifierAt >= 0 && draftIdx.length > 0 && verifierAt > draftIdx[0]!) {
    bad("verifier_result must come before the first draft");
  }
  const lastTerminal = types.reduce(
    (at, t, i) => (t === "subagent_done" || t === "subagent_failed" ? i : at),
    -1,
  );
  if (verifierAt >= 0 && lastTerminal > verifierAt) bad("verifier_result must follow every sub-agent");
  if (draftIdx.length > 0 && draftIdx.at(-1)! + 1 !== events.length - 1) {
    bad("drafts must be contiguous and immediately followed by run_done");
  }
  draftIdx.forEach((at, n) => {
    const e = events[at] as Of<"draft">;
    if (e.sections.length !== 1) bad(`draft ${n} must carry exactly one section`);
    else if (n < SECTION_IDS.length && e.sections[0]!.id !== SECTION_IDS[n]) bad(`draft ${n} must be ${SECTION_IDS[n]}`);
    if (e.complete !== (n === draftIdx.length - 1)) bad(`draft ${n}: only the last draft is complete`);
  });

  const state = new Map<string, { open: boolean; closed: boolean; calls: Set<string> }>();
  events.forEach((e, i) => {
    if (
      e.type === "tool_call" ||
      e.type === "tool_result" ||
      e.type === "retry" ||
      e.type === "subagent_started" ||
      e.type === "subagent_done" ||
      e.type === "subagent_failed"
    ) {
      let s = state.get(e.agent);
      if (e.type === "subagent_started") {
        if (s) bad(`${e.agent} started more than once`);
        state.set(e.agent, { open: true, closed: false, calls: new Set() });
        return;
      }
      if (!s?.open) {
        bad(`${e.type} for ${e.agent} at index ${i} is outside its started..done window`);
        s = s ?? { open: false, closed: false, calls: new Set() };
      }
      if (e.type === "tool_call") s.calls.add(e.call_id);
      else if (e.type === "tool_result" && !s.calls.delete(e.call_id)) {
        bad(`tool_result ${e.call_id} has no matching tool_call`);
      } else if (e.type === "subagent_done" || e.type === "subagent_failed") {
        s.open = false;
        s.closed = true;
      }
    }
  });
  for (const [agent, s] of state) if (!s.closed) bad(`${agent} never finished`);
  return errors;
}

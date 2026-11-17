import { assemblePack, type AgentEvent } from "@mpa/contract";
import { describe, expect, it } from "vitest";
import { chatReducer, initialChat, isRunning } from "@/lib/chat";
import { deriveView, initRun, runReducer, type RunAction, type RunState } from "@/lib/run";
import { loadRun } from "./helpers";

const feed = (events: readonly AgentEvent[], state = initRun("hi", undefined, 0)) =>
  events.reduce<RunState>((s, event) => runReducer(s, { type: "event", event }), state);

const shuffle = <T,>(items: T[], seed = 7): T[] => {
  const out = [...items];
  let x = seed;
  for (let i = out.length - 1; i > 0; i--) {
    x = (x * 1103515245 + 12345) % 2 ** 31;
    const j = x % (i + 1);
    [out[i], out[j]] = [out[j]!, out[i]!];
  }
  return out;
};

describe("runReducer", () => {
  it("finishes on run_done and keeps events ordered by seq", () => {
    const { events } = loadRun("brightmoor.normal");
    const state = feed(events);
    expect(state.status).toBe("done");
    expect(state.events.map((e) => e.seq)).toEqual(events.map((e) => e.seq));
  });

  it("is order-independent: shuffled arrival gives the same sorted events", () => {
    const { events } = loadRun("brightmoor.news_down");
    for (const seed of [1, 2, 3]) {
      const mid = feed(shuffle(events, seed).filter((e) => e.type !== "run_done"));
      expect(mid.events.map((e) => e.seq)).toEqual(
        events.filter((e) => e.type !== "run_done").map((e) => e.seq),
      );
      expect(mid.status).toBe("running");
    }
  });

  it("ignores duplicate seq and counts events from another run as skipped", () => {
    const { events } = loadRun("brightmoor.normal");
    const dup = feed([events[0]!, events[0]!, events[1]!]);
    expect(dup.events).toHaveLength(2);
    const foreign = runReducer(dup, { type: "event", event: { ...events[2]!, run_id: "other" } });
    expect(foreign.events).toHaveLength(2);
    expect(foreign.skipped).toBe(1);
  });

  it("ignores events after the run is no longer running", () => {
    const { events } = loadRun("brightmoor.normal");
    const done = feed(events);
    expect(runReducer(done, { type: "event", event: events[0]! })).toBe(done);
  });

  it("turns a stream that ends early into unexpected_end, but never overrides done", () => {
    const { events } = loadRun("brightmoor.normal");
    const cut = feed(events.slice(0, 10));
    expect(runReducer(cut, { type: "stream_end" }).status).toBe("unexpected_end");
    const done = feed(events);
    expect(runReducer(done, { type: "stream_end" })).toBe(done);
  });

  it.each<[RunAction, string]>([
    [{ type: "stopped" }, "stopped"],
    [{ type: "failed", kind: "unreachable", detail: "x" }, "failed"],
    [{ type: "skipped" }, "running"],
  ])("handles %o", (action, status) => {
    expect(runReducer(initRun("m", undefined, 0), action).status).toBe(status);
  });
});

describe("deriveView", () => {
  it("builds four lanes with per-agent status for the news-down run", () => {
    const { events } = loadRun("brightmoor.news_down");
    const view = deriveView(events, true);
    const status = Object.fromEntries(view.lanes.map((l) => [l.agent, l.status]));
    expect(status).toEqual({
      correspondence: "done",
      documents: "done",
      news: "failed",
      attendees: "done",
    });
    expect(view.partial).toBe(true);
    expect(view.gaps.some((g) => g.source === "news")).toBe(true);
  });

  it("shows retrying while a retry is the latest event for an agent", () => {
    const { events } = loadRun("brightmoor.news_down");
    const retryAt = events.findIndex((e) => e.type === "retry" && e.agent === "news");
    const view = deriveView(events.slice(0, retryAt + 1), false);
    expect(view.lanes.find((l) => l.agent === "news")?.status).toBe("retrying");
    const after = deriveView(events.slice(0, retryAt + 2), false);
    expect(after.lanes.find((l) => l.agent === "news")?.status).toBe("retrying");
  });

  it("is queued before any agent starts and running after tool calls resume", () => {
    const { events } = loadRun("brightmoor.normal");
    const planOnly = deriveView(events.slice(0, 2), false);
    expect(planOnly.lanes.map((l) => l.status)).toEqual(["queued", "queued", "queued", "queued"]);
    expect(planOnly.writing).toBe(false);
    const running = deriveView(events.slice(0, 8), false);
    expect(running.lanes.every((l) => l.status === "running")).toBe(true);
  });

  it("matches assemblePack for every fixture run and exposes stats", () => {
    for (const name of ["brightmoor.normal", "brightmoor.news_down", "halden.budget_hit"] as const) {
      const { events, pack } = loadRun(name);
      const view = deriveView(events, true);
      expect(view.pack).toEqual(pack);
      expect(view.pack).toEqual(assemblePack(shuffle(events)));
      expect(view.stats).toEqual(pack.stats);
      expect(view.sections.map((s) => s.id)).toEqual(pack.sections.map((s) => s.id));
    }
  });

  it("records the budget hit and counts steps live from tool_call events", () => {
    const { events } = loadRun("halden.budget_hit");
    const view = deriveView(events, true);
    expect(view.budgetHit?.budget).toBeDefined();
    expect(view.steps).toBe(events.filter((e) => e.type === "tool_call").length);
  });

  it("reveals sections as draft events arrive", () => {
    const { events } = loadRun("brightmoor.normal");
    const firstDraft = events.findIndex((e) => e.type === "draft");
    const verifierAt = events.findIndex((e) => e.type === "verifier_result");
    expect(deriveView(events.slice(0, verifierAt), false).writing).toBe(false);
    expect(deriveView(events.slice(0, verifierAt + 1), false).sections).toHaveLength(0);
    const view = deriveView(events.slice(0, firstDraft + 2), false);
    expect(view.writing).toBe(true);
    expect(view.sections).toHaveLength(2);
    expect(view.pack).toBeNull();
  });

  it("falls back to failures only when the pack cannot be assembled", () => {
    const { events } = loadRun("brightmoor.news_down");
    const view = deriveView(events.filter((e) => e.type !== "plan"), true);
    expect(view.pack).toBeNull();
    expect(view.gaps.map((g) => g.source)).toEqual(["news"]);
  });
});

describe("chatReducer", () => {
  it("starts, updates and restarts turns independently", () => {
    let s = chatReducer(initialChat, {
      type: "turn_start", id: 1, message: "a", failSource: "news", at: 5,
    });
    s = chatReducer(s, { type: "turn_start", id: 2, message: "b", failSource: undefined, at: 6 });
    s = chatReducer(s, { type: "turn_action", id: 1, action: { type: "stopped" } });
    expect(s.turns.map((t) => t.run.status)).toEqual(["stopped", "running"]);
    expect(isRunning(s)).toBe(true);
    s = chatReducer(s, { type: "turn_restart", id: 1, at: 9 });
    expect(s.turns[0]!.run).toMatchObject({ status: "running", message: "a", failSource: "news", startedAt: 9 });
  });
});

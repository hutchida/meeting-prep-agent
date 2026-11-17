import { z } from "zod";
import { AGENT_NAMES, CalId, GAP_REASONS, Gap, IsoDateTime, Stats } from "./common";
import { BriefingSection, VerifierCounts, SECTION_IDS } from "./briefing";

const agent = z.enum(AGENT_NAMES);
const base = {
  run_id: z.string().min(1).max(64),
  seq: z.number().int().min(0),
  ts: IsoDateTime,
};

export const RunStartedEvent = z
  .strictObject({
    ...base,
    type: z.literal("run_started"),
    message: z.string().max(2000),
    model: z.string().min(1).max(100),
  })
  .meta({ id: "RunStartedEvent" });

export const PlanEvent = z
  .strictObject({
    ...base,
    type: z.literal("plan"),
    client: z.string().min(1).max(100),
    meeting_id: CalId,
    // Optional in the schema for additivity, but always sent; assemblePack needs both.
    meeting_title: z.string().min(1).max(200).optional(),
    meeting_start: IsoDateTime.optional(),
    tasks: z.array(z.strictObject({ agent, goal: z.string().max(300) }).meta({ id: "PlanTask" })).max(8),
  })
  .meta({ id: "PlanEvent" });

export const SubagentStartedEvent = z
  .strictObject({
    ...base,
    type: z.literal("subagent_started"),
    agent,
    goal: z.string().max(300),
  })
  .meta({ id: "SubagentStartedEvent" });

export const ToolCallEvent = z
  .strictObject({
    ...base,
    type: z.literal("tool_call"),
    agent,
    call_id: z.string().min(1).max(64),
    tool: z.string().min(1).max(64),
    args: z.record(z.string(), z.union([z.string().max(200), z.number(), z.boolean()])),
  })
  .meta({ id: "ToolCallEvent" });

export const ToolResultEvent = z
  .strictObject({
    ...base,
    type: z.literal("tool_result"),
    agent,
    call_id: z.string().min(1).max(64),
    tool: z.string().min(1).max(64),
    ok: z.boolean(),
    item_count: z.number().int().min(0),
    ids: z.array(z.string().regex(/^[ECDNPM][0-9]{1,9}$/)).max(10),
    summary: z.string().max(300),
    duration_ms: z.number().int().min(0),
  })
  .meta({ id: "ToolResultEvent" });

export const RetryEvent = z
  .strictObject({
    ...base,
    type: z.literal("retry"),
    agent,
    attempt: z.number().int().min(1),
    backoff_ms: z.number().int().min(0),
    error: z.string().max(300),
  })
  .meta({ id: "RetryEvent" });

export const SubagentFailedEvent = z
  .strictObject({
    ...base,
    type: z.literal("subagent_failed"),
    agent,
    reason: z.enum(GAP_REASONS),
    error: z.string().max(300),
  })
  .meta({ id: "SubagentFailedEvent" });

export const SubagentDoneEvent = z
  .strictObject({
    ...base,
    type: z.literal("subagent_done"),
    agent,
    findings_count: z.number().int().min(0),
    gaps: z.array(Gap).max(12),
    duration_ms: z.number().int().min(0),
  })
  .meta({ id: "SubagentDoneEvent" });

/**
 * One verified section per event, in canonical order (7 events, only the last has `complete`).
 * A whole BriefingPack can be 40 KB, far above the 8 KB event limit, so clients rebuild it with
 * `assemblePack` (see EVENTS.md).
 */
export const DraftEvent = z
  .strictObject({
    ...base,
    type: z.literal("draft"),
    sections: z.array(BriefingSection).min(1).max(SECTION_IDS.length),
    complete: z.boolean(),
  })
  .meta({ id: "DraftEvent" });

export const DROP_REASONS = ["no_citation", "invalid_citation", "unsupported", "injection"] as const;

export const VerifierResultEvent = z
  .strictObject({
    ...base,
    type: z.literal("verifier_result"),
    verifier: VerifierCounts,
    dropped: z
      .array(
        z
          .strictObject({
            section_id: z.enum(SECTION_IDS),
            reason: z.enum(DROP_REASONS),
            text: z.string().max(200),
          })
          .meta({ id: "DroppedSentence" }),
      )
      .max(10),
  })
  .meta({ id: "VerifierResultEvent" });

export const BUDGET_KINDS = ["steps", "tokens", "cost", "time"] as const;

export const BudgetHitEvent = z
  .strictObject({
    ...base,
    type: z.literal("budget_hit"),
    budget: z.enum(BUDGET_KINDS),
    limit: z.number().min(0),
    used: z.number().min(0),
  })
  .meta({ id: "BudgetHitEvent" });

export const RunDoneEvent = z
  .strictObject({
    ...base,
    type: z.literal("run_done"),
    partial: z.boolean(),
    stats: Stats,
  })
  .meta({ id: "RunDoneEvent" });

export const AGENT_EVENT_TYPES = [
  "run_started",
  "plan",
  "subagent_started",
  "tool_call",
  "tool_result",
  "retry",
  "subagent_failed",
  "subagent_done",
  "draft",
  "verifier_result",
  "budget_hit",
  "run_done",
] as const;

export const AgentEvent = z
  .discriminatedUnion("type", [
    RunStartedEvent,
    PlanEvent,
    SubagentStartedEvent,
    ToolCallEvent,
    ToolResultEvent,
    RetryEvent,
    SubagentFailedEvent,
    SubagentDoneEvent,
    DraftEvent,
    VerifierResultEvent,
    BudgetHitEvent,
    RunDoneEvent,
  ])
  .meta({ id: "AgentEvent" });
export type AgentEvent = z.infer<typeof AgentEvent>;

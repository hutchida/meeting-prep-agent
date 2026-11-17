import { z } from "zod";

/**
 * Canonical timestamp format used everywhere in the contract: ISO-8601, UTC only,
 * `YYYY-MM-DDTHH:MM:SS` with an optional `.sss` millisecond part, always suffixed `Z`.
 * Offsets such as `+00:00` are NOT accepted. Digits are ASCII `[0-9]` so the same pattern
 * behaves identically in ECMAScript and Rust (Pydantic) regex engines.
 */
export const ISO_DATETIME_PATTERN =
  "^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\\.[0-9]{3})?Z$";

export const IsoDateTime = z
  .string()
  .regex(new RegExp(ISO_DATETIME_PATTERN))
  .describe("ISO-8601 UTC timestamp: YYYY-MM-DDTHH:MM:SS[.sss]Z");

export const CITATION_TYPES = ["email", "chat", "doc", "news", "contact", "cal"] as const;
export const CitationType = z.enum(CITATION_TYPES);
export type CitationType = z.infer<typeof CitationType>;

export const ID_PREFIX = {
  email: "E",
  chat: "C",
  doc: "D",
  news: "N",
  contact: "P",
  cal: "M",
} as const satisfies Record<CitationType, string>;

export const idOf = (prefix: string) => z.string().regex(new RegExp(`^${prefix}[0-9]{1,9}$`));

export const EmailId = idOf("E");
export const ChatId = idOf("C");
export const DocId = idOf("D");
export const NewsId = idOf("N");
export const ContactId = idOf("P");
export const CalId = idOf("M");

/** Any item id (any of the six prefixes). */
export const AnyItemId = z.string().regex(/^[ECDNPM][0-9]{1,9}$/);

export const AGENT_NAMES = ["correspondence", "documents", "news", "attendees"] as const;
export const AgentName = z.enum(AGENT_NAMES);
export type AgentName = z.infer<typeof AgentName>;

export const GAP_SOURCES = ["email", "chat", "docs", "news", "calendar", "contacts"] as const;
export const GAP_REASONS = ["timeout", "fault_injected", "budget", "error"] as const;

export const Gap = z
  .strictObject({
    source: z.enum(GAP_SOURCES),
    reason: z.enum(GAP_REASONS),
    detail: z.string().max(300),
  })
  .meta({ id: "Gap", description: "A part of the briefing that is missing, and why." });
export type Gap = z.infer<typeof Gap>;

export const Stats = z
  .strictObject({
    steps: z.number().int().min(0),
    tokens_in: z.number().int().min(0),
    tokens_out: z.number().int().min(0),
    cost_usd: z.number().min(0),
    duration_ms: z.number().int().min(0),
  })
  .meta({ id: "Stats" });
export type Stats = z.infer<typeof Stats>;

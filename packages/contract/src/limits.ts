export const LIMITS = {
  AGENT_EVENT_MAX_BYTES: 8192,
  BRIEFING_PACK_MAX_BYTES: 40960,
  TOOL_RESULT_MAX_ITEMS: 10,
  TOOL_RESULT_ITEM_MAX_BYTES: 4096,
  EMAIL_MAX_BYTES: 6144,
} as const;

export type LimitKind = "agent_event" | "briefing_pack" | "tool_result" | "email";

export class LimitError extends Error {
  constructor(
    readonly kind: LimitKind,
    message: string,
  ) {
    super(message);
    this.name = "LimitError";
  }
}

/** UTF-8 bytes of the compact JSON serialisation (the unit all size limits use). */
export function jsonBytes(value: unknown): number {
  return new TextEncoder().encode(JSON.stringify(value)).length;
}

/** Throws `LimitError` if `value` is over the size limit for `kind`. Does not validate shape. */
export function assertWithinLimit(kind: LimitKind, value: unknown): void {
  const fail = (msg: string): never => {
    throw new LimitError(kind, `${kind}: ${msg}`);
  };
  const check = (max: number, label = "") => {
    const size = jsonBytes(value);
    if (size > max) fail(`${label}${size} bytes exceeds ${max}`);
  };
  switch (kind) {
    case "agent_event":
      return check(LIMITS.AGENT_EVENT_MAX_BYTES);
    case "briefing_pack":
      return check(LIMITS.BRIEFING_PACK_MAX_BYTES);
    case "email":
      return check(LIMITS.EMAIL_MAX_BYTES);
    case "tool_result": {
      const items = (value as { items?: unknown }).items;
      if (!Array.isArray(items)) return fail("missing items array");
      if (items.length > LIMITS.TOOL_RESULT_MAX_ITEMS) {
        fail(`${items.length} items exceeds ${LIMITS.TOOL_RESULT_MAX_ITEMS}`);
      }
      items.forEach((item, i) => {
        const size = jsonBytes(item);
        if (size > LIMITS.TOOL_RESULT_ITEM_MAX_BYTES) {
          fail(`item ${i} is ${size} bytes, exceeds ${LIMITS.TOOL_RESULT_ITEM_MAX_BYTES}`);
        }
      });
      return;
    }
  }
}

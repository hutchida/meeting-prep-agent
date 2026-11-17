import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020";
import { describe, expect, it } from "vitest";
import {
  AgentEvent,
  BriefingPack,
  LIMITS,
  SCHEMAS,
  SECTION_IDS,
  assertWithinLimit,
  buildJsonSchemas,
  citationToken,
  parseCitations,
  serializeJsonSchema,
  type LimitKind,
  type SchemaName,
} from "../src/index";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const fixtureDir = join(root, "fixtures");
const schemaDir = join(root, "schema");

const readJson = (path: string): unknown => JSON.parse(readFileSync(path, "utf8"));
const jsonFiles = (dir: string) => readdirSync(dir).filter((f) => f.endsWith(".json")).sort();
const schemaNameOf = (file: string) => file.split(".")[0] as string;

const ajv = new Ajv2020({ strict: true, allErrors: false });
const validators = Object.fromEntries(
  Object.keys(SCHEMAS).map((name) => [name, ajv.compile(readJson(join(schemaDir, `${name}.json`)) as object)]),
);

const LIMIT_KIND: Partial<Record<SchemaName, LimitKind>> = {
  AgentEvent: "agent_event",
  BriefingPack: "briefing_pack",
  ToolResult: "tool_result",
  Email: "email",
};

describe("json schema export", () => {
  it("committed schema/*.json equals a fresh export", () => {
    const fresh = buildJsonSchemas();
    expect(jsonFiles(schemaDir)).toEqual(Object.keys(fresh).sort().map((n) => `${n}.json`));
    for (const [name, schema] of Object.entries(fresh)) {
      expect(readFileSync(join(schemaDir, `${name}.json`), "utf8"), name).toBe(serializeJsonSchema(schema));
    }
  });

  it("is draft 2020-12 and every object is closed", () => {
    for (const [name, schema] of Object.entries(buildJsonSchemas())) {
      expect(schema.$schema, name).toBe("https://json-schema.org/draft/2020-12/schema");
      const open: string[] = [];
      const walk = (node: unknown, path: string) => {
        if (Array.isArray(node)) return node.forEach((n, i) => walk(n, `${path}[${i}]`));
        if (node === null || typeof node !== "object") return;
        const obj = node as Record<string, unknown>;
        const isRecord = typeof obj.additionalProperties === "object" && obj.propertyNames !== undefined;
        if (obj.type === "object" && obj.additionalProperties !== false && !isRecord) open.push(path);
        for (const [k, v] of Object.entries(obj)) walk(v, `${path}.${k}`);
      };
      walk(schema, name);
      expect(open, `open objects in ${name}`).toEqual([]);
    }
  });
});

describe("fixtures", () => {
  const valid = jsonFiles(fixtureDir).filter((f) => f !== "citation_cases.json");
  const invalid = jsonFiles(join(fixtureDir, "invalid"));

  it("every fixture file names a known schema", () => {
    for (const f of [...valid, ...invalid]) expect(Object.keys(SCHEMAS), f).toContain(schemaNameOf(f));
  });

  it("covers every schema, every AgentEvent variant and the three pack shapes", () => {
    const names = new Set(valid.map(schemaNameOf));
    for (const n of Object.keys(SCHEMAS)) expect(names.has(n), `fixture for ${n}`).toBe(true);
    for (const t of [
      "run_started", "plan", "subagent_started", "tool_call", "tool_result", "retry",
      "subagent_failed", "subagent_done", "draft", "verifier_result", "budget_hit", "run_done",
    ]) {
      expect(valid, t).toContain(`AgentEvent.${t}.json`);
    }
    for (const v of ["full", "partial_news_down", "empty_news"]) expect(valid).toContain(`BriefingPack.${v}.json`);
    for (const n of ["Email", "ChatMessage", "Doc", "CalendarEvent", "Contact", "NewsItem", "EvalResult"]) {
      expect(names.has(n)).toBe(true);
    }
  });

  it.each(valid)("valid fixture %s passes zod, JSON Schema and size limits", (file) => {
    const name = schemaNameOf(file) as SchemaName;
    const value = readJson(join(fixtureDir, file));
    expect(SCHEMAS[name].safeParse(value).success, "zod").toBe(true);
    const validate = validators[name]!;
    expect(validate(value), JSON.stringify(validate.errors)).toBe(true);
    const kind = LIMIT_KIND[name];
    if (kind) assertWithinLimit(kind, value);
  });

  it.each(invalid)("invalid fixture %s is rejected", (file) => {
    const name = schemaNameOf(file) as SchemaName;
    const value = readJson(join(fixtureDir, "invalid", file));
    if (file.includes(".over_limit") || file.includes(".item_over_limit")) {
      // Structurally fine; only the size limit rejects it.
      expect(SCHEMAS[name].safeParse(value).success, "zod").toBe(true);
      expect(validators[name]!(value)).toBe(true);
      expect(() => assertWithinLimit(LIMIT_KIND[name]!, value)).toThrow(/exceeds/);
    } else {
      expect(SCHEMAS[name].safeParse(value).success, "zod").toBe(false);
      expect(validators[name]!(value), "json schema").toBe(false);
    }
  });
});

describe("size limits", () => {
  it("exposes the fixed limits", () => {
    expect(LIMITS).toEqual({
      AGENT_EVENT_MAX_BYTES: 8192,
      BRIEFING_PACK_MAX_BYTES: 40960,
      TOOL_RESULT_MAX_ITEMS: 10,
      TOOL_RESULT_ITEM_MAX_BYTES: 4096,
      EMAIL_MAX_BYTES: 6144,
    });
  });

  it("just-under fixtures sit close to the limit", () => {
    const size = (f: string) => new TextEncoder().encode(JSON.stringify(readJson(join(fixtureDir, f)))).length;
    expect(size("AgentEvent.just_under_limit.json")).toBeGreaterThan(LIMITS.AGENT_EVENT_MAX_BYTES - 100);
    expect(size("BriefingPack.just_under_limit.json")).toBeGreaterThan(LIMITS.BRIEFING_PACK_MAX_BYTES - 100);
    expect(size("Email.just_under_limit.json")).toBeGreaterThan(LIMITS.EMAIL_MAX_BYTES - 100);
  });

  it("rejects more than 10 tool result items and counts UTF-8 bytes, not characters", () => {
    const tooMany = readJson(join(fixtureDir, "invalid", "ToolResult.too_many_items.json"));
    expect(() => assertWithinLimit("tool_result", tooMany)).toThrow(/items exceeds/);
    const multibyte = { items: [{ text: "é".repeat(2049) }] };
    expect(() => assertWithinLimit("tool_result", multibyte)).toThrow(/exceeds 4096/);
    expect(() => assertWithinLimit("tool_result", { items: [{ text: "é".repeat(2040) }] })).not.toThrow();
  });
});

describe("contract rules", () => {
  const pack = readJson(join(fixtureDir, "BriefingPack.full.json")) as { sections: { id: string }[] };

  it("pack sections are fixed in order and id", () => {
    expect(pack.sections.map((s) => s.id)).toEqual([...SECTION_IDS]);
  });

  it("a note sentence may lack citations but a fact sentence may not", () => {
    const clone = structuredClone(pack) as unknown as { sections: { sentences: unknown[] }[] };
    clone.sections[2]!.sentences = [{ text: "No recent news found.", citations: [], kind: "note" }];
    expect(BriefingPack.safeParse(clone).success).toBe(true);
    clone.sections[2]!.sentences = [{ text: "A fact.", citations: [], kind: "fact" }];
    expect(BriefingPack.safeParse(clone).success).toBe(false);
    clone.sections[2]!.sentences = [{ text: "A fact.", citations: [] }];
    expect(BriefingPack.safeParse(clone).success).toBe(false);
  });

  it("AgentEvent discriminates on type and rejects unknown types", () => {
    const base = { run_id: "r", seq: 0, ts: "2026-03-09T09:00:00Z" };
    expect(AgentEvent.safeParse({ ...base, type: "run_done", partial: false, stats: { steps: 0, tokens_in: 0, tokens_out: 0, cost_usd: 0, duration_ms: 0 } }).success).toBe(true);
    expect(AgentEvent.safeParse({ ...base, type: "nope" }).success).toBe(false);
  });

  it("timestamps must be canonical UTC", () => {
    const ok = ["2026-03-09T09:00:00Z", "2026-03-09T09:00:00.123Z"];
    const bad = ["2026-03-09T09:00:00+00:00", "2026-03-09 09:00:00Z", "2026-13-09T09:00:00Z", "2026-03-09T09:00:00.1Z", "2026-03-09"];
    const shape = AgentEvent.options.find((o) => o.shape.type.value === "run_started")!;
    for (const ts of ok) expect(shape.safeParse({ run_id: "r", seq: 0, ts, type: "run_started", message: "m", model: "x" }).success, ts).toBe(true);
    for (const ts of bad) expect(shape.safeParse({ run_id: "r", seq: 0, ts, type: "run_started", message: "m", model: "x" }).success, ts).toBe(false);
  });
});

describe("citation helpers", () => {
  const cases = readJson(join(fixtureDir, "citation_cases.json")) as {
    parse: { name: string; text: string; expected: unknown[] }[];
    token: { citation: { type: string; id: string }; token: string }[];
    token_invalid: { type: string; id: string }[];
  };

  it.each(cases.parse)("parseCitations: $name", ({ text, expected }) => {
    expect(parseCitations(text)).toEqual(expected);
  });
  it.each(cases.token)("citationToken: $token", ({ citation, token }) => {
    expect(citationToken(citation as never)).toBe(token);
  });
  it.each(cases.token_invalid)("citationToken rejects $type:$id", (citation) => {
    expect(() => citationToken(citation as never)).toThrow();
  });
  it("round-trips", () => {
    for (const { citation } of cases.token) {
      expect(parseCitations(citationToken(citation as never))).toEqual([citation]);
    }
  });
});

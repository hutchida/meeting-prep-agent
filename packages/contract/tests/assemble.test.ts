import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020";
import { describe, expect, it } from "vitest";
import {
  AgentEvent,
  BriefingPack,
  LIMITS,
  PackAssemblyError,
  SECTION_IDS,
  assemblePack,
  checkEventOrder,
  jsonBytes,
} from "../src/index";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const runsDir = join(root, "fixtures", "runs");
const readJson = (path: string): unknown => JSON.parse(readFileSync(path, "utf8"));

type Json = Record<string, unknown>;
const ajv = new Ajv2020({ strict: true });
const validateEvent = ajv.compile(readJson(join(root, "schema", "AgentEvent.json")) as object);
const validatePack = ajv.compile(readJson(join(root, "schema", "BriefingPack.json")) as object);

const streams = readdirSync(runsDir)
  .filter((f) => f.endsWith(".events.json"))
  .map((f) => f.replace(".events.json", ""))
  .sort();
const events = (name: string) => readJson(join(runsDir, `${name}.events.json`)) as AgentEvent[];
const pack = (name: string) => readJson(join(runsDir, `${name}.pack.json`));

interface Op extends Json {
  op: string;
  where?: Json;
  path?: string;
}
interface Case {
  name: string;
  stream: string;
  ops: Op[];
  expect?: { equals_pack?: boolean; checks?: Json; error?: string };
  errors_contain?: string[];
}
const cases = readJson(join(runsDir, "assemble_cases.json")) as { assemble: Case[]; order: Case[] };

const matches = (e: Json, where: Json = {}) => Object.entries(where).every(([k, v]) => e[k] === v);
const setPath = (target: unknown, path: string, value: unknown, remove = false) => {
  const keys = path.split(".");
  let node = target as Record<string, unknown>;
  for (const k of keys.slice(0, -1)) node = node[k] as Record<string, unknown>;
  const last = keys.at(-1)!;
  if (remove) delete node[last];
  else node[last] = value;
};

function applyOps(input: AgentEvent[], ops: Op[]): AgentEvent[] {
  let list = structuredClone(input) as unknown as Json[];
  for (const op of ops) {
    const at = list.findIndex((e) => matches(e, op.where));
    switch (op.op) {
      case "reverse":
        list = list.reverse();
        break;
      case "rotate":
        list = [...list.slice(op.by as number), ...list.slice(0, op.by as number)];
        break;
      case "keep_first":
        list = list.slice(0, op.count as number);
        break;
      case "drop":
        list = list.filter((e) => !matches(e, op.where));
        break;
      case "clone":
        list.push({ ...structuredClone(list[at]!), seq: op.new_seq });
        break;
      case "move": {
        const [e] = list.splice(at, 1);
        list.splice(op.to_index as number, 0, e!);
        break;
      }
      case "set":
        for (const e of list.filter((x) => matches(x, op.where))) setPath(e, op.path!, op.value);
        break;
      case "delete":
        for (const e of list.filter((x) => matches(x, op.where))) setPath(e, op.path!, undefined, true);
        break;
      default:
        throw new Error(`unknown op ${op.op}`);
    }
  }
  return list as unknown as AgentEvent[];
}

const lookup = (value: unknown, path: string) =>
  path.split(".").reduce<unknown>((n, k) => (n as Record<string, unknown>)[k], value);

describe("run fixtures", () => {
  it("has the three expected streams", () => {
    expect(streams).toEqual(["run.brightmoor.news_down", "run.brightmoor.normal", "run.halden.budget_hit"]);
  });

  describe.each(streams)("%s", (name) => {
    const list = events(name);

    it("every event validates (zod, JSON Schema) and is under 8 KB", () => {
      for (const e of list) {
        expect(AgentEvent.safeParse(e).success, `zod seq ${e.seq}`).toBe(true);
        expect(validateEvent(e), JSON.stringify(validateEvent.errors)).toBe(true);
        expect(jsonBytes(e)).toBeLessThanOrEqual(LIMITS.AGENT_EVENT_MAX_BYTES);
      }
    });

    it("seq is strictly increasing and the event order rules hold", () => {
      list.forEach((e, i) => i > 0 && expect(e.seq).toBeGreaterThan(list[i - 1]!.seq));
      expect(checkEventOrder(list)).toEqual([]);
    });

    it("the expected pack is valid and under 40 KB", () => {
      const expected = pack(name);
      expect(BriefingPack.safeParse(expected).success).toBe(true);
      expect(validatePack(expected), JSON.stringify(validatePack.errors)).toBe(true);
      expect(jsonBytes(expected)).toBeLessThanOrEqual(LIMITS.BRIEFING_PACK_MAX_BYTES);
    });

    it("assemblePack rebuilds the expected pack", () => {
      expect(assemblePack(list)).toEqual(pack(name));
    });

    it("verifier counts match the sentences in the pack", () => {
      const p = pack(name) as { sections: { sentences: unknown[] }[]; verifier: Json };
      const kept = p.sections.reduce((n, s) => n + s.sentences.length, 0);
      expect(p.verifier.sentences_kept).toBe(kept);
      expect(p.verifier.sentences_total).toBe(kept + (p.verifier.sentences_dropped as number));
    });
  });

  it("normal run has all four agents with tool calls, interleaved, and at least 25 events", () => {
    const list = events("run.brightmoor.normal");
    expect(list.length).toBeGreaterThanOrEqual(25);
    const agents = new Set(list.filter((e) => e.type === "tool_call").map((e) => (e as { agent: string }).agent));
    expect([...agents].sort()).toEqual(["attendees", "correspondence", "documents", "news"]);
    const seq = list.filter((e) => "agent" in e).map((e) => (e as { agent: string }).agent);
    expect(seq.some((a, i) => i > 0 && a !== seq[i - 1])).toBe(true);
    expect(list.some((e) => e.type === "retry")).toBe(true);
  });

  it("news_down run: retry then subagent_failed, a note in recent_news, partial", () => {
    const list = events("run.brightmoor.news_down");
    const types = list.filter((e) => "agent" in e && (e as { agent: string }).agent === "news").map((e) => e.type);
    expect(types.indexOf("retry")).toBeLessThan(types.indexOf("subagent_failed"));
    const p = pack("run.brightmoor.news_down") as { partial: boolean; sections: { id: string; sentences: { text: string; kind?: string }[] }[] };
    expect(p.partial).toBe(true);
    const news = p.sections.find((s) => s.id === "recent_news")!;
    expect(news.sentences).toHaveLength(1);
    expect(news.sentences[0]!.kind).toBe("note");
    expect(news.sentences[0]!.text).toContain("could not be reached");
  });

  it("budget_hit run has a budget_hit and gaps", () => {
    const list = events("run.halden.budget_hit");
    expect(list.filter((e) => e.type === "budget_hit")).toHaveLength(1);
    const p = pack("run.halden.budget_hit") as { partial: boolean; gaps: unknown[] };
    expect(p.partial).toBe(true);
    expect(p.gaps.length).toBeGreaterThan(0);
  });
});

describe("assemblePack cases", () => {
  it.each(cases.assemble)("$name", (c) => {
    const input = applyOps(events(c.stream), c.ops);
    if (c.expect?.error) {
      expect(() => assemblePack(input)).toThrow(PackAssemblyError);
      expect(() => assemblePack(input)).toThrow(c.expect.error);
      return;
    }
    const result = assemblePack(input);
    if (c.expect?.equals_pack) expect(result).toEqual(pack(c.stream));
    for (const [path, value] of Object.entries(c.expect?.checks ?? {})) {
      expect(lookup(result, path), path).toEqual(value);
    }
  });

  it("always emits seven sections in canonical order", () => {
    for (const c of cases.assemble.filter((x) => !x.expect?.error)) {
      const result = assemblePack(applyOps(events(c.stream), c.ops));
      expect(result.sections.map((s) => s.id)).toEqual([...SECTION_IDS]);
    }
  });
});

describe("checkEventOrder cases", () => {
  it.each(cases.order)("$name", (c) => {
    const errors = checkEventOrder(applyOps(events(c.stream), c.ops));
    for (const part of c.errors_contain ?? []) {
      expect(errors.some((e) => e.includes(part)), `${part} in ${JSON.stringify(errors)}`).toBe(true);
    }
  });
});

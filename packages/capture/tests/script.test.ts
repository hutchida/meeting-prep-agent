import path from "node:path";
import { describe, expect, it } from "vitest";
import demo, { SECTION_IDS } from "../scripts/demo";
import { loadScript, normalizeScript, resolveScriptPath } from "../src/script";
import { click, validateSteps } from "../src/steps";

describe("script loading", () => {
  it("resolves scripts by name and by path", () => {
    const byName = resolveScriptPath("demo");
    expect(path.basename(byName)).toBe("demo.ts");
    expect(resolveScriptPath(byName)).toBe(byName);
    expect(() => resolveScriptPath("nope-not-there")).toThrow(/No capture script/);
    expect(() => resolveScriptPath("./missing.ts")).toThrow(/not found/);
  });

  it("loads the demo script and validates it", async () => {
    const def = await loadScript("demo", { live: false });
    expect(def.name).toBe("demo");
    expect(validateSteps(def.steps)).toEqual([]);
  });

  it("accepts plain objects and rejects malformed exports", () => {
    const ok = normalizeScript({ name: "x", steps: [click({ testId: "a" })] }, { live: false });
    expect(ok.name).toBe("x");
    expect(() => normalizeScript(null, { live: false })).toThrow();
    expect(() => normalizeScript({ steps: [] }, { live: false })).toThrow(/name/);
    expect(() => normalizeScript({ name: "x", steps: [] }, { live: false })).toThrow(/Invalid steps/);
  });
});

describe("demo script", () => {
  const limit = (def: ReturnType<typeof demo>) => def.steps.find((s) => s.kind === "expectMarkWithin");

  it("uses 10 s in replay and 90 s in live mode, overridable", () => {
    expect(limit(demo({ live: false }))).toMatchObject({ maxMs: 10_000 });
    expect(limit(demo({ live: true }))).toMatchObject({ maxMs: 90_000 });
    expect(limit(demo({ live: true, maxBriefingMs: 5000 }))).toMatchObject({ maxMs: 5000 });
  });

  it("covers all seven sections and the contract test ids", () => {
    expect(SECTION_IDS).toHaveLength(7);
    const text = JSON.stringify(demo({ live: false }).steps);
    for (const id of [
      "starter-brightmoor",
      "step-timeline",
      "briefing",
      "citation",
      "source-panel",
      "source-panel-close",
      "toggle-news-outage",
      "chat-input",
      "chat-send",
      ...SECTION_IDS.map((s) => `section-${s}`),
    ]) {
      expect(text).toContain(id);
    }
  });

  it("limits the whole replay run to 60 s", () => {
    expect(demo({ live: false }).totalTimeoutMs).toBe(60_000);
  });
});

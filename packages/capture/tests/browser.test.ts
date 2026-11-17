import { existsSync, mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import demo from "../scripts/demo";
import { runCapture } from "../src/capture";
import { startFixtureServer, type FixtureServer } from "../src/fixture";
import { click, expectText, goto, screenshot, toggle, waitForTestId } from "../src/steps";
import { parseGif, RUN_BROWSER } from "./helpers";

describe.skipIf(!RUN_BROWSER)("runCapture against the fixture page", () => {
  let server: FixtureServer;
  let out: string;

  beforeAll(async () => {
    server = await startFixtureServer();
    out = mkdtempSync(path.join(tmpdir(), "mpa-capture-"));
  });

  afterAll(async () => {
    await server.close();
    rmSync(out, { recursive: true, force: true });
  });

  it("runs the demo script, writing screenshots and a valid GIF", async () => {
    const def = demo({ live: false });
    const result = await runCapture({
      name: def.name,
      baseUrl: server.url,
      steps: def.steps,
      outDir: path.join(out, "nested", "media"),
      totalTimeoutMs: def.totalTimeoutMs ?? 60_000,
    });
    expect(result.failedStep).toBeUndefined();
    expect(result.ok).toBe(true);
    expect(result.durationMs).toBeLessThan(60_000);
    expect(result.screenshots.map((s) => path.basename(s))).toEqual([
      "demo-01-home.png",
      "demo-02-timeline.png",
      "demo-03-briefing.png",
      "demo-04-source-panel.png",
      "demo-05-outage-timeline.png",
      "demo-06-outage-briefing.png",
    ]);
    for (const s of result.screenshots) expect(statSync(s).size).toBeGreaterThan(1000);
    expect(result.marks["briefing-ready"]).toBeGreaterThanOrEqual(result.marks["prompt-sent"] ?? Infinity);
    expect(result.gif && path.basename(result.gif)).toBe("demo.gif");
    const gif = readFileSync(result.gif as string);
    const info = parseGif(gif);
    expect(info.header).toBe("GIF89a");
    expect(info.trailer).toBe(true);
    expect(info.width).toBeLessThanOrEqual(960);
    expect(info.frames).toBeGreaterThan(5);
    expect(gif.length).toBeLessThan(4 * 1024 * 1024);
  });

  it("overwrites files with deterministic names and can skip the GIF", async () => {
    const steps = [goto("/"), screenshot("home")];
    const a = await runCapture({ name: "again", baseUrl: server.url, steps, outDir: out, gif: false });
    const b = await runCapture({ name: "again", baseUrl: server.url, steps, outDir: out, gif: false });
    expect(a.screenshots).toEqual(b.screenshots);
    expect(a.gif).toBeUndefined();
    expect(existsSync(path.join(out, "again.gif"))).toBe(false);
  });

  it("toggle is idempotent when a target state is given", async () => {
    const result = await runCapture({
      name: "toggle",
      baseUrl: server.url,
      outDir: out,
      gif: false,
      steps: [
        goto("/"),
        toggle({ testId: "toggle-news-outage" }, true),
        toggle({ testId: "toggle-news-outage" }, true),
        click({ testId: "starter-halden" }),
        waitForTestId("briefing"),
        expectText({ testId: "section-recent_news" }, "could not be reached"),
      ],
    });
    expect(result.ok).toBe(true);
  });

  it("reports the failed step with target, screenshot and no env values", async () => {
    process.env.CAPTURE_TEST_SECRET_KEY = "never-print-this-value-42";
    try {
      const result = await runCapture({
        name: "fails",
        baseUrl: server.url,
        outDir: out,
        steps: [
          goto("/"),
          waitForTestId("does-not-exist", { timeoutMs: 400, name: "wait for ghost" }),
          screenshot("never-reached"),
        ],
      });
      expect(result.ok).toBe(false);
      expect(result.steps).toHaveLength(2);
      const failed = result.failedStep;
      expect(failed).toMatchObject({ index: 2, name: "wait for ghost", target: "testId=does-not-exist" });
      expect(failed?.screenshot && existsSync(failed.screenshot)).toBe(true);
      expect(path.basename(failed?.screenshot ?? "")).toBe("fails-failed-02.png");
      expect(JSON.stringify(result)).not.toContain("never-print-this-value");
      expect(result.gif).toBeDefined();
    } finally {
      delete process.env.CAPTURE_TEST_SECRET_KEY;
    }
  });

  it("fails the demo when the briefing is slower than the limit", async () => {
    const slow = await startFixtureServer({ briefingDelayMs: 1500 });
    try {
      const def = demo({ live: false, maxBriefingMs: 500 });
      const result = await runCapture({
        name: "slow",
        baseUrl: slow.url,
        steps: def.steps,
        outDir: out,
        gif: false,
      });
      expect(result.ok).toBe(false);
      expect(result.failedStep?.error).toMatch(/took \d+ms, limit 500ms/);
    } finally {
      await slow.close();
    }
  });

  it("stops at the total timeout", async () => {
    const result = await runCapture({
      name: "budget",
      baseUrl: server.url,
      outDir: out,
      gif: false,
      totalTimeoutMs: 800,
      steps: [goto("/"), waitForTestId("nope", { timeoutMs: 60_000 })],
    });
    expect(result.ok).toBe(false);
    expect(result.durationMs).toBeLessThan(5000);
  });
});

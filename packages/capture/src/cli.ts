import path from "node:path";
import { parseArgs } from "node:util";
import { runCapture, formatFailure, type CaptureResult } from "./capture";
import { startFixtureServer, type FixtureServer } from "./fixture";
import { loadScript } from "./script";

const USAGE = `Usage: pnpm --filter @mpa/capture run capture -- <script.ts|name> [options]
  --base <url>            App base URL (default http://localhost:3000)
  --out <dir>             Output directory (default docs/media)
  --no-gif                Skip the animated GIF
  --headed                Show the browser window
  --live                  Live-LLM mode (briefing limit 90000 ms)
  --max-briefing-ms <n>   Override the briefing time limit
  --fixture               Run against the built-in fixture page instead of the app`;

function show(file: string, base: string): string {
  const rel = path.relative(base, file);
  return rel.startsWith("..") ? file : rel;
}

function table(result: CaptureResult): string {
  const rows = result.steps.map((s) => [String(s.index), s.name, `${s.ms}`, s.status]);
  const widths = [4, 0, 7, 6].map((w, c) => Math.max(w, ...rows.map((r) => (r[c] ?? "").length)));
  const line = (r: string[]) =>
    r.map((cell, c) => (c === 2 ? cell.padStart(widths[c] ?? 0) : cell.padEnd(widths[c] ?? 0))).join("  ");
  return [line(["#", "step", "ms", "status"]), ...rows.map(line)].join("\n");
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2).filter((a, i) => !(i === 0 && a === "--"));
  const { values, positionals } = parseArgs({
    args: argv,
    allowPositionals: true,
    options: {
      base: { type: "string" },
      out: { type: "string" },
      "no-gif": { type: "boolean", default: false },
      headed: { type: "boolean", default: false },
      live: { type: "boolean", default: false },
      "max-briefing-ms": { type: "string" },
      fixture: { type: "boolean", default: false },
      help: { type: "boolean", default: false },
    },
  });
  const spec = positionals[0];
  if (values.help || !spec) {
    console.log(USAGE);
    return values.help ? 0 : 1;
  }

  const maxBriefing = values["max-briefing-ms"] ? Number(values["max-briefing-ms"]) : undefined;
  if (maxBriefing !== undefined && !(maxBriefing > 0)) throw new Error("--max-briefing-ms must be > 0");
  const script = await loadScript(spec, {
    live: values.live,
    ...(maxBriefing !== undefined ? { maxBriefingMs: maxBriefing } : {}),
  });

  let fixture: FixtureServer | undefined;
  try {
    if (values.fixture) fixture = await startFixtureServer();
    const baseUrl = fixture?.url ?? values.base ?? script.baseUrl ?? "http://localhost:3000";
    const initCwd = process.env.INIT_CWD ?? process.cwd();
    const outDir = values.out ? path.resolve(initCwd, values.out) : undefined;

    console.log(`capture ${script.name} (${script.steps.length} steps)`);
    const result = await runCapture({
      name: script.name,
      baseUrl,
      steps: script.steps,
      ...(outDir ? { outDir } : {}),
      gif: !values["no-gif"],
      headless: !values.headed,
      ...(script.viewport ? { viewport: script.viewport } : {}),
      ...(script.totalTimeoutMs ? { totalTimeoutMs: script.totalTimeoutMs } : {}),
      ...(script.gifFrameDelayMs ? { gifFrameDelayMs: script.gifFrameDelayMs } : {}),
    });

    console.log(table(result));
    console.log(`\nduration: ${result.durationMs} ms`);
    if (Object.keys(result.marks).length > 0) console.log(`marks: ${JSON.stringify(result.marks)}`);
    for (const n of result.notes) console.log(`note: ${n}`);
    for (const s of result.screenshots) console.log(`screenshot: ${show(s, initCwd)}`);
    if (result.gif && result.gifInfo) {
      const i = result.gifInfo;
      console.log(
        `gif: ${show(result.gif, initCwd)} (${i.frames} frames, ${i.width}x${i.height}, ${(i.bytes / 1024).toFixed(0)} KiB)`,
      );
    }
    for (const w of result.warnings) console.log(`warning: ${w}`);
    if (!result.ok) {
      console.error(`\nFAILED: ${formatFailure(result)}`);
      return 1;
    }
    console.log("\nOK");
    return 0;
  } finally {
    await fixture?.close();
  }
}

main().then(
  (code) => process.exit(code),
  (error: unknown) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  },
);

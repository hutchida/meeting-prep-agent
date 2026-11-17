import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { chromium, type Browser, type Page } from "playwright";
import { assembleGif, type GifResult } from "./gif";
import { failedFileName, resolveOutDir, shotFileName } from "./paths";
import { errorMessage, redact } from "./redact";
import { assertValidSteps, describeTarget, slugify, type CountBounds, type Step } from "./steps";
import { resolveOne, resolveTarget } from "./targets";

export interface CaptureOptions {
  name: string;
  baseUrl: string;
  steps: Step[];
  outDir?: string;
  viewport?: { width: number; height: number };
  gif?: boolean;
  gifFrameDelayMs?: number;
  headless?: boolean;
  totalTimeoutMs?: number;
  stepTimeoutMs?: number;
  maxGifBytes?: number;
  onStep?: (result: StepResult) => void;
}

export interface StepResult {
  index: number;
  name: string;
  kind: Step["kind"];
  ms: number;
  status: "ok" | "failed";
  error?: string;
}

export interface FailedStep {
  index: number;
  name: string;
  target?: string;
  error: string;
  screenshot?: string;
}

export interface CaptureResult {
  ok: boolean;
  name: string;
  screenshots: string[];
  gif?: string;
  gifInfo?: Omit<GifResult, "buffer">;
  marks: Record<string, number>;
  notes: string[];
  steps: StepResult[];
  warnings: string[];
  durationMs: number;
  failedStep?: FailedStep;
}

export const DEFAULT_VIEWPORT = { width: 1280, height: 800 };
export const DEFAULT_TOTAL_TIMEOUT_MS = 120_000;
export const DEFAULT_STEP_TIMEOUT_MS = 10_000;
const POLL_MS = 100;

export class StepFailure extends Error {}

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

async function pollUntil(
  check: () => Promise<string | null>,
  timeoutMs: number,
  what: string,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let reason = "";
  for (;;) {
    try {
      const r = await check();
      if (r === null) return;
      reason = r;
    } catch (e) {
      reason = errorMessage(e);
    }
    if (Date.now() >= deadline) {
      throw new StepFailure(`${what} not satisfied within ${timeoutMs}ms (${reason})`);
    }
    await sleep(Math.min(POLL_MS, Math.max(1, deadline - Date.now())));
  }
}

function matches(actual: string, pattern: string | RegExp): boolean {
  return typeof pattern === "string" ? actual.includes(pattern) : pattern.test(actual);
}

function boundsFailure(count: number, b: CountBounds): string | null {
  if (b.exactly !== undefined && count !== b.exactly) return `count ${count}, expected exactly ${b.exactly}`;
  if (b.atLeast !== undefined && count < b.atLeast) return `count ${count}, expected at least ${b.atLeast}`;
  if (b.atMost !== undefined && count > b.atMost) return `count ${count}, expected at most ${b.atMost}`;
  return null;
}

function stepTarget(step: Step): string | undefined {
  if ("target" in step && step.target) return describeTarget(step.target);
  if (step.kind === "waitForTestId" || step.kind === "waitForNoTestId") return `testId=${step.testId}`;
  return undefined;
}

interface RunState {
  page: Page;
  baseUrl: string;
  name: string;
  outDir: string;
  marks: Record<string, number>;
  notes: string[];
  screenshots: string[];
  shotOrdinal: number;
  elapsed: () => number;
}

async function executeStep(state: RunState, step: Step, timeoutMs: number): Promise<void> {
  const { page } = state;
  switch (step.kind) {
    case "goto": {
      const url = new URL(step.url, state.baseUrl).toString();
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: timeoutMs });
      return;
    }
    case "click":
      await resolveOne(page, step.target).click({ timeout: timeoutMs });
      return;
    case "fill":
      await resolveOne(page, step.target).fill(step.text, { timeout: timeoutMs });
      return;
    case "press":
      if (step.target) await resolveOne(page, step.target).press(step.key, { timeout: timeoutMs });
      else await page.keyboard.press(step.key);
      return;
    case "toggle": {
      const loc = resolveOne(page, step.target);
      const read = (): Promise<boolean | null> =>
        loc.evaluate((el) => {
          if (el instanceof HTMLInputElement && /checkbox|radio/.test(el.type)) return el.checked;
          for (const attr of ["aria-checked", "aria-pressed"]) {
            const v = el.getAttribute(attr);
            if (v === "true") return true;
            if (v === "false") return false;
          }
          const ds = el.getAttribute("data-state");
          if (ds === "checked" || ds === "on") return true;
          if (ds === "unchecked" || ds === "off") return false;
          return null;
        }, { timeout: timeoutMs });
      const before = await read();
      if (step.on !== undefined && before === step.on) return;
      await loc.click({ timeout: timeoutMs });
      if (step.on !== undefined) {
        const want = step.on;
        await pollUntil(
          async () => {
            const now = await read();
            return now === null || now === want ? null : `toggle is ${now ? "on" : "off"}`;
          },
          Math.min(timeoutMs, 2000),
          `toggle ${want ? "on" : "off"}`,
        );
      }
      return;
    }
    case "waitForText":
      await pollUntil(
        async () =>
          (await page.getByText(step.text).first().isVisible()) ? null : "text not visible",
        timeoutMs,
        `text ${String(step.text)}`,
      );
      return;
    case "waitForTestId":
      await pollUntil(
        async () => ((await page.getByTestId(step.testId).first().isVisible()) ? null : "not visible"),
        timeoutMs,
        `testId ${step.testId} visible`,
      );
      return;
    case "waitFor":
      await pollUntil(
        async () => ((await resolveOne(page, step.target).isVisible()) ? null : "not visible"),
        timeoutMs,
        `${describeTarget(step.target)} visible`,
      );
      return;
    case "waitForNoTestId":
      await pollUntil(
        async () => ((await page.getByTestId(step.testId).first().isVisible()) ? "still visible" : null),
        timeoutMs,
        `testId ${step.testId} gone`,
      );
      return;
    case "wait":
      await sleep(step.ms);
      return;
    case "screenshot": {
      state.shotOrdinal += 1;
      const file = path.join(
        state.outDir,
        shotFileName(state.name, state.shotOrdinal, slugify(step.label)),
      );
      await page.screenshot({ path: file, fullPage: step.fullPage, timeout: timeoutMs });
      state.screenshots.push(file);
      return;
    }
    case "expectVisible":
      await pollUntil(
        async () => ((await resolveOne(page, step.target).isVisible()) ? null : "not visible"),
        timeoutMs,
        `${describeTarget(step.target)} visible`,
      );
      return;
    case "expectText":
      await pollUntil(
        async () => {
          const loc = resolveOne(page, step.target);
          if ((await loc.count()) === 0) return "element not found";
          const text = (await loc.innerText({ timeout: 1000 })) ?? "";
          return matches(text, step.text) ? null : `text was ${text.length} chars, no match`;
        },
        timeoutMs,
        `${describeTarget(step.target)} text ${String(step.text)}`,
      );
      return;
    case "expectCount":
      await pollUntil(
        async () => boundsFailure(await resolveTarget(page, step.target).count(), step.bounds),
        timeoutMs,
        `${describeTarget(step.target)} count ${JSON.stringify(step.bounds)}`,
      );
      return;
    case "expectDistinctAttr":
      await pollUntil(
        async () => {
          const values = await resolveTarget(page, step.target).evaluateAll(
            (els, attr) => els.map((e) => e.getAttribute(attr) ?? ""),
            step.attr,
          );
          const distinct = new Set(values.filter((v) => v !== ""));
          return distinct.size >= step.atLeast ? null : `${distinct.size} distinct`;
        },
        timeoutMs,
        `${describeTarget(step.target)} >= ${step.atLeast} distinct [${step.attr}]`,
      );
      return;
    case "mark":
      state.marks[step.label] = state.elapsed();
      return;
    case "expectMarkWithin": {
      const end = state.marks[step.label];
      const start = state.marks[step.since];
      if (end === undefined || start === undefined) {
        throw new StepFailure(`marks ${step.since} / ${step.label} were not recorded`);
      }
      const took = end - start;
      if (took > step.maxMs) {
        throw new StepFailure(`${step.since} -> ${step.label} took ${took}ms, limit ${step.maxMs}ms`);
      }
      return;
    }
    case "note":
      state.notes.push(redact(step.text));
      return;
  }
}

const NO_FRAME_KINDS: ReadonlySet<Step["kind"]> = new Set(["mark", "note"]);

export async function runCapture(options: CaptureOptions): Promise<CaptureResult> {
  assertValidSteps(options.steps);
  const name = slugify(options.name);
  if (name === "") throw new Error("capture name must contain letters or digits");
  const outDir = resolveOutDir(options.outDir ?? "docs/media");
  const viewport = options.viewport ?? DEFAULT_VIEWPORT;
  const totalTimeoutMs = options.totalTimeoutMs ?? DEFAULT_TOTAL_TIMEOUT_MS;
  const stepTimeoutMs = options.stepTimeoutMs ?? DEFAULT_STEP_TIMEOUT_MS;
  const wantGif = options.gif ?? true;

  await mkdir(outDir, { recursive: true });

  const started = performance.now();
  let overhead = 0;
  const state: RunState = {
    page: undefined as unknown as Page,
    baseUrl: options.baseUrl,
    name,
    outDir,
    marks: {},
    notes: [],
    screenshots: [],
    shotOrdinal: 0,
    elapsed: () => Math.round(performance.now() - started - overhead),
  };
  const result: CaptureResult = {
    ok: true,
    name,
    screenshots: state.screenshots,
    marks: state.marks,
    notes: state.notes,
    steps: [],
    warnings: [],
    durationMs: 0,
  };
  const frames: Buffer[] = [];

  let browser: Browser | undefined;
  let watchdog: NodeJS.Timeout | undefined;
  try {
    try {
      browser = await chromium.launch({ headless: options.headless ?? true });
    } catch (e) {
      const msg = errorMessage(e);
      throw new Error(
        /executable doesn't exist|browserType\.launch/i.test(msg)
          ? "Chromium is not installed. Run: pnpm --filter @mpa/capture run install-browsers"
          : `Could not launch Chromium: ${msg}`,
      );
    }
    const launched = browser;
    watchdog = setTimeout(() => void launched.close().catch(() => undefined), totalTimeoutMs + 15_000);
    watchdog.unref();

    const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
    state.page = await context.newPage();

    for (const [i, step] of options.steps.entries()) {
      const index = i + 1;
      const t0 = performance.now();
      const remaining = totalTimeoutMs - (performance.now() - started);
      let error: string | undefined;
      try {
        if (remaining <= 0) throw new StepFailure(`total timeout of ${totalTimeoutMs}ms exceeded`);
        const timeout = Math.max(1, Math.min(step.timeoutMs ?? stepTimeoutMs, remaining));
        await executeStep(state, step, timeout);
      } catch (e) {
        error = errorMessage(e);
      }
      const ms = Math.round(performance.now() - t0);
      const stepResult: StepResult = {
        index,
        name: step.name,
        kind: step.kind,
        ms,
        status: error === undefined ? "ok" : "failed",
        ...(error === undefined ? {} : { error }),
      };
      result.steps.push(stepResult);
      options.onStep?.(stepResult);

      const c0 = performance.now();
      let failedShot: string | undefined;
      try {
        if (error !== undefined) {
          failedShot = path.join(outDir, failedFileName(name, index));
          const png = await state.page.screenshot({ path: failedShot, timeout: 5000 });
          state.screenshots.push(failedShot);
          frames.push(png);
        } else if (wantGif && !NO_FRAME_KINDS.has(step.kind)) {
          frames.push(await state.page.screenshot({ timeout: 5000 }));
        }
      } catch {
        failedShot = undefined;
      }
      overhead += performance.now() - c0;

      if (error !== undefined) {
        const target = stepTarget(step);
        result.ok = false;
        result.failedStep = {
          index,
          name: step.name,
          ...(target ? { target } : {}),
          error,
          ...(failedShot ? { screenshot: failedShot } : {}),
        };
        break;
      }
    }
  } finally {
    if (watchdog) clearTimeout(watchdog);
    await browser?.close().catch(() => undefined);
  }

  result.durationMs = Math.round(performance.now() - started);

  if (wantGif && frames.length > 0) {
    const gif = assembleGif(frames, {
      ...(options.gifFrameDelayMs !== undefined ? { frameDelayMs: options.gifFrameDelayMs } : {}),
      ...(options.maxGifBytes !== undefined ? { maxBytes: options.maxGifBytes } : {}),
    });
    const gifPath = path.join(outDir, `${name}.gif`);
    await writeFile(gifPath, gif.buffer);
    result.gif = gifPath;
    const { buffer: _buffer, ...info } = gif;
    void _buffer;
    result.gifInfo = info;
    if (!gif.withinCap) result.warnings.push(`GIF is ${gif.bytes} bytes, above the size cap`);
  }
  return result;
}

export function formatFailure(result: CaptureResult): string {
  const f = result.failedStep;
  if (!f) return "";
  const parts = [`Step ${f.index} "${f.name}" failed`];
  if (f.target) parts.push(`target: ${f.target}`);
  parts.push(f.error);
  if (f.screenshot) parts.push(`screenshot: ${f.screenshot}`);
  return redact(parts.join(" | "));
}

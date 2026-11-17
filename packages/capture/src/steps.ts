export type Target =
  | { testId: string; nth?: number }
  | { text: string | RegExp; exact?: boolean; nth?: number }
  | { role: string; name?: string | RegExp; exact?: boolean; nth?: number }
  | { css: string; nth?: number };

export interface StepOptions {
  name?: string;
  timeoutMs?: number;
}

export interface StepBase {
  name: string;
  timeoutMs?: number;
}

export interface CountBounds {
  atLeast?: number;
  atMost?: number;
  exactly?: number;
}

export type Step =
  | (StepBase & { kind: "goto"; url: string })
  | (StepBase & { kind: "click"; target: Target })
  | (StepBase & { kind: "fill"; target: Target; text: string })
  | (StepBase & { kind: "press"; key: string; target?: Target })
  | (StepBase & { kind: "toggle"; target: Target; on?: boolean })
  | (StepBase & { kind: "waitForText"; text: string | RegExp })
  | (StepBase & { kind: "waitForTestId"; testId: string })
  | (StepBase & { kind: "waitFor"; target: Target })
  | (StepBase & { kind: "waitForNoTestId"; testId: string })
  | (StepBase & { kind: "wait"; ms: number })
  | (StepBase & { kind: "screenshot"; label: string; fullPage: boolean })
  | (StepBase & { kind: "expectVisible"; target: Target })
  | (StepBase & { kind: "expectText"; target: Target; text: string | RegExp })
  | (StepBase & { kind: "expectCount"; target: Target; bounds: CountBounds })
  | (StepBase & { kind: "expectDistinctAttr"; target: Target; attr: string; atLeast: number })
  | (StepBase & { kind: "mark"; label: string })
  | (StepBase & { kind: "expectMarkWithin"; label: string; since: string; maxMs: number })
  | (StepBase & { kind: "note"; text: string });

export type StepKind = Step["kind"];

export const STEP_KINDS: readonly StepKind[] = [
  "goto",
  "click",
  "fill",
  "press",
  "toggle",
  "waitForText",
  "waitForTestId",
  "waitFor",
  "waitForNoTestId",
  "wait",
  "screenshot",
  "expectVisible",
  "expectText",
  "expectCount",
  "expectDistinctAttr",
  "mark",
  "expectMarkWithin",
  "note",
];

export function describeTarget(target: Target): string {
  let base: string;
  if ("testId" in target) base = `testId=${target.testId}`;
  else if ("css" in target) base = `css=${target.css}`;
  else if ("role" in target) {
    base = `role=${target.role}`;
    if (target.name !== undefined) base += `[name=${String(target.name)}]`;
  } else base = `text=${typeof target.text === "string" ? JSON.stringify(target.text) : String(target.text)}`;
  return target.nth === undefined ? base : `${base}#${target.nth}`;
}

export function slugify(label: string): string {
  return label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}

const t = (target: Target): string => describeTarget(target);
const patternText = (p: string | RegExp): string => (typeof p === "string" ? JSON.stringify(p) : String(p));

export function goto(pathOrUrl: string, opts: StepOptions = {}): Step {
  let shown = pathOrUrl;
  if (/^https?:\/\//i.test(pathOrUrl)) {
    try {
      const u = new URL(pathOrUrl);
      shown = u.origin + u.pathname;
    } catch {
      shown = "<invalid url>";
    }
  }
  return { kind: "goto", url: pathOrUrl, ...opts, name: opts.name ?? `goto ${shown}` };
}

export function click(target: Target, opts: StepOptions = {}): Step {
  return { kind: "click", target, ...opts, name: opts.name ?? `click ${t(target)}` };
}

export function fill(target: Target, text: string, opts: StepOptions = {}): Step {
  return { kind: "fill", target, text, ...opts, name: opts.name ?? `fill ${t(target)}` };
}

export function press(key: string, opts: StepOptions & { target?: Target } = {}): Step {
  const { target, ...rest } = opts;
  return {
    kind: "press",
    key,
    ...(target ? { target } : {}),
    ...rest,
    name: opts.name ?? `press ${key}`,
  };
}

export function toggle(target: Target, on?: boolean, opts: StepOptions = {}): Step {
  const state = on === undefined ? "flip" : on ? "on" : "off";
  return {
    kind: "toggle",
    target,
    ...(on === undefined ? {} : { on }),
    ...opts,
    name: opts.name ?? `toggle ${state} ${t(target)}`,
  };
}

export function waitForText(text: string | RegExp, opts: StepOptions = {}): Step {
  return { kind: "waitForText", text, ...opts, name: opts.name ?? `waitForText ${patternText(text)}` };
}

export function waitForTestId(testId: string, opts: StepOptions = {}): Step {
  return { kind: "waitForTestId", testId, ...opts, name: opts.name ?? `waitForTestId ${testId}` };
}

export function waitFor(target: Target, opts: StepOptions = {}): Step {
  return { kind: "waitFor", target, ...opts, name: opts.name ?? `waitFor ${t(target)}` };
}

export function waitForNoTestId(testId: string, opts: StepOptions = {}): Step {
  return {
    kind: "waitForNoTestId",
    testId,
    ...opts,
    name: opts.name ?? `waitForNoTestId ${testId}`,
  };
}

export function wait(ms: number, opts: StepOptions = {}): Step {
  return { kind: "wait", ms, ...opts, name: opts.name ?? `wait ${ms}ms` };
}

export function screenshot(
  label: string,
  opts: StepOptions & { fullPage?: boolean } = {},
): Step {
  const { fullPage, ...rest } = opts;
  return {
    kind: "screenshot",
    label,
    fullPage: fullPage ?? false,
    ...rest,
    name: opts.name ?? `screenshot ${label}`,
  };
}

export function expectVisible(target: Target, opts: StepOptions = {}): Step {
  return { kind: "expectVisible", target, ...opts, name: opts.name ?? `expectVisible ${t(target)}` };
}

export function expectText(
  target: Target,
  text: string | RegExp,
  opts: StepOptions = {},
): Step {
  return {
    kind: "expectText",
    target,
    text,
    ...opts,
    name: opts.name ?? `expectText ${t(target)} ~ ${patternText(text)}`,
  };
}

export function expectCount(
  target: Target,
  bounds: CountBounds,
  opts: StepOptions = {},
): Step {
  return {
    kind: "expectCount",
    target,
    bounds,
    ...opts,
    name: opts.name ?? `expectCount ${t(target)} ${JSON.stringify(bounds)}`,
  };
}

export function expectDistinctAttr(
  target: Target,
  attr: string,
  atLeast: number,
  opts: StepOptions = {},
): Step {
  return {
    kind: "expectDistinctAttr",
    target,
    attr,
    atLeast,
    ...opts,
    name: opts.name ?? `expectDistinctAttr ${t(target)} [${attr}] >= ${atLeast}`,
  };
}

export function mark(label: string, opts: StepOptions = {}): Step {
  return { kind: "mark", label, ...opts, name: opts.name ?? `mark ${label}` };
}

export function expectMarkWithin(
  label: string,
  since: string,
  maxMs: number,
  opts: StepOptions = {},
): Step {
  return {
    kind: "expectMarkWithin",
    label,
    since,
    maxMs,
    ...opts,
    name: opts.name ?? `expectMarkWithin ${since} -> ${label} <= ${maxMs}ms`,
  };
}

export function note(text: string, opts: StepOptions = {}): Step {
  return { kind: "note", text, ...opts, name: opts.name ?? "note" };
}

function validateTarget(target: unknown, where: string, problems: string[]): void {
  if (typeof target !== "object" || target === null) {
    problems.push(`${where}: target must be an object`);
    return;
  }
  const rec = target as Record<string, unknown>;
  const keys = ["testId", "text", "role", "css"].filter((k) => rec[k] !== undefined);
  if (keys.length !== 1) {
    problems.push(`${where}: target needs exactly one of testId/text/role/css (got ${keys.length})`);
    return;
  }
  const key = keys[0] as string;
  const value = rec[key];
  const isRegex = value instanceof RegExp;
  if (key === "text" && !(isRegex || (typeof value === "string" && value.length > 0))) {
    problems.push(`${where}: target.text must be a non-empty string or RegExp`);
  } else if (key !== "text" && !(typeof value === "string" && value.length > 0)) {
    problems.push(`${where}: target.${key} must be a non-empty string`);
  }
  if (rec.nth !== undefined && !Number.isInteger(rec.nth)) {
    problems.push(`${where}: target.nth must be an integer`);
  }
  if (key === "role" && rec.name !== undefined) {
    if (!(typeof rec.name === "string" || rec.name instanceof RegExp)) {
      problems.push(`${where}: target.name must be a string or RegExp`);
    }
  }
}

function validatePattern(value: unknown, where: string, problems: string[]): void {
  if (value instanceof RegExp) return;
  if (typeof value !== "string" || value.length === 0) {
    problems.push(`${where}: expected a non-empty string or RegExp`);
  }
}

export function validateSteps(steps: unknown): string[] {
  const problems: string[] = [];
  if (!Array.isArray(steps) || steps.length === 0) return ["steps must be a non-empty array"];
  const marks = new Set<string>();
  steps.forEach((raw: unknown, i) => {
    const where = `step ${i + 1}`;
    if (typeof raw !== "object" || raw === null) {
      problems.push(`${where}: must be an object`);
      return;
    }
    const s = raw as Record<string, unknown>;
    if (!STEP_KINDS.includes(s.kind as StepKind)) {
      problems.push(`${where}: unknown kind ${JSON.stringify(s.kind)}`);
      return;
    }
    if (typeof s.name !== "string" || s.name.trim() === "") problems.push(`${where}: name is required`);
    if (s.timeoutMs !== undefined) {
      const ms = s.timeoutMs;
      if (typeof ms !== "number" || !Number.isFinite(ms) || ms <= 0 || ms > 600_000) {
        problems.push(`${where}: timeoutMs must be a number in (0, 600000]`);
      }
    }
    switch (s.kind as StepKind) {
      case "goto":
        if (typeof s.url !== "string" || s.url.length === 0) {
          problems.push(`${where}: goto needs a path or url`);
        } else if (!s.url.startsWith("/") && !/^https?:\/\//i.test(s.url)) {
          problems.push(`${where}: goto must be a path starting with "/" or an http(s) url`);
        }
        break;
      case "click":
      case "waitFor":
      case "expectVisible":
        validateTarget(s.target, where, problems);
        break;
      case "fill":
        validateTarget(s.target, where, problems);
        if (typeof s.text !== "string") problems.push(`${where}: fill text must be a string`);
        break;
      case "press":
        if (typeof s.key !== "string" || s.key.length === 0) problems.push(`${where}: press needs a key`);
        if (s.target !== undefined) validateTarget(s.target, where, problems);
        break;
      case "toggle":
        validateTarget(s.target, where, problems);
        if (s.on !== undefined && typeof s.on !== "boolean") problems.push(`${where}: toggle on must be boolean`);
        break;
      case "waitForText":
        validatePattern(s.text, `${where}: text`, problems);
        break;
      case "waitForTestId":
      case "waitForNoTestId":
        if (typeof s.testId !== "string" || s.testId.length === 0) problems.push(`${where}: testId is required`);
        break;
      case "wait":
        if (typeof s.ms !== "number" || !(s.ms >= 0) || s.ms > 60_000) {
          problems.push(`${where}: wait ms must be in [0, 60000]`);
        }
        break;
      case "screenshot":
        if (typeof s.label !== "string" || slugify(s.label) === "") {
          problems.push(`${where}: screenshot label must contain letters or digits`);
        }
        break;
      case "expectText":
        validateTarget(s.target, where, problems);
        validatePattern(s.text, `${where}: text`, problems);
        break;
      case "expectCount": {
        validateTarget(s.target, where, problems);
        const b = s.bounds as CountBounds | undefined;
        const vals = b ? [b.atLeast, b.atMost, b.exactly] : [];
        if (!b || vals.every((v) => v === undefined)) {
          problems.push(`${where}: expectCount needs atLeast, atMost or exactly`);
        } else if (vals.some((v) => v !== undefined && (!Number.isInteger(v) || (v as number) < 0))) {
          problems.push(`${where}: expectCount bounds must be non-negative integers`);
        }
        break;
      }
      case "expectDistinctAttr":
        validateTarget(s.target, where, problems);
        if (typeof s.attr !== "string" || s.attr.length === 0) problems.push(`${where}: attr is required`);
        if (!Number.isInteger(s.atLeast) || (s.atLeast as number) < 1) {
          problems.push(`${where}: atLeast must be an integer >= 1`);
        }
        break;
      case "mark":
        if (typeof s.label !== "string" || s.label.length === 0) {
          problems.push(`${where}: mark label is required`);
        } else if (marks.has(s.label)) {
          problems.push(`${where}: duplicate mark label ${JSON.stringify(s.label)}`);
        } else marks.add(s.label);
        break;
      case "expectMarkWithin":
        for (const k of ["label", "since"] as const) {
          const v = s[k];
          if (typeof v !== "string" || !marks.has(v)) {
            problems.push(`${where}: ${k} ${JSON.stringify(v)} must reference an earlier mark`);
          }
        }
        if (typeof s.maxMs !== "number" || !(s.maxMs > 0)) problems.push(`${where}: maxMs must be > 0`);
        break;
      case "note":
        if (typeof s.text !== "string" || s.text.length === 0) problems.push(`${where}: note text is required`);
        break;
    }
  });
  return problems;
}

export function assertValidSteps(steps: unknown): asserts steps is Step[] {
  const problems = validateSteps(steps);
  if (problems.length > 0) throw new Error(`Invalid steps:\n- ${problems.join("\n- ")}`);
}

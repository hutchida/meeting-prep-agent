import { existsSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { findRepoRoot } from "./paths";
import { assertValidSteps, type Step } from "./steps";

export interface ScriptContext {
  live: boolean;
  maxBriefingMs?: number;
}

export interface ScriptDefinition {
  name: string;
  steps: Step[];
  baseUrl?: string;
  viewport?: { width: number; height: number };
  totalTimeoutMs?: number;
  gifFrameDelayMs?: number;
}

export type ScriptModuleExport = ScriptDefinition | ((ctx: ScriptContext) => ScriptDefinition);

export function scriptsDir(): string {
  return path.join(findRepoRoot(), "packages", "capture", "scripts");
}

export function resolveScriptPath(spec: string, cwd: string = process.cwd()): string {
  const looksLikePath = /[\\/]/.test(spec) || /\.(ts|mts|js|mjs)$/.test(spec);
  if (looksLikePath) {
    const abs = path.resolve(cwd, spec);
    if (!existsSync(abs)) throw new Error(`Capture script not found: ${spec}`);
    return abs;
  }
  for (const ext of [".ts", ".mts", ".js", ".mjs"]) {
    const candidate = path.join(scriptsDir(), `${spec}${ext}`);
    if (existsSync(candidate)) return candidate;
  }
  throw new Error(`No capture script named "${spec}" in packages/capture/scripts`);
}

export function normalizeScript(exported: unknown, ctx: ScriptContext): ScriptDefinition {
  const def = typeof exported === "function" ? (exported as (c: ScriptContext) => unknown)(ctx) : exported;
  if (typeof def !== "object" || def === null) {
    throw new Error("Capture script must default-export { name, steps } or a function returning it");
  }
  const rec = def as Record<string, unknown>;
  if (typeof rec.name !== "string" || rec.name.trim() === "") {
    throw new Error("Capture script needs a non-empty string `name`");
  }
  if (rec.baseUrl !== undefined && typeof rec.baseUrl !== "string") {
    throw new Error("Capture script `baseUrl` must be a string");
  }
  assertValidSteps(rec.steps);
  return def as ScriptDefinition;
}

export async function loadScript(spec: string, ctx: ScriptContext): Promise<ScriptDefinition> {
  const file = resolveScriptPath(spec);
  const mod = (await import(pathToFileURL(file).href)) as { default?: unknown };
  if (mod.default === undefined) throw new Error(`Capture script ${path.basename(file)} has no default export`);
  return normalizeScript(mod.default, ctx);
}

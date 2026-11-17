import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export function findRepoRoot(start: string = path.dirname(fileURLToPath(import.meta.url))): string {
  let dir = start;
  for (;;) {
    if (existsSync(path.join(dir, "pnpm-workspace.yaml"))) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) return process.cwd();
    dir = parent;
  }
}

export function resolveOutDir(outDir: string, root: string = findRepoRoot()): string {
  return path.isAbsolute(outDir) ? outDir : path.resolve(root, outDir);
}

export function shotFileName(name: string, ordinal: number, label: string): string {
  return `${name}-${String(ordinal).padStart(2, "0")}-${label}.png`;
}

export function failedFileName(name: string, stepIndex: number): string {
  return `${name}-failed-${String(stepIndex).padStart(2, "0")}.png`;
}

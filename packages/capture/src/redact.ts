const SENSITIVE_NAME = /(KEY|SECRET|TOKEN|PASSWORD|PASSWD|AUTH|COOKIE|CREDENTIAL|URL|LANGFUSE|DSN)/i;

const KEY_VALUE = /\b(api[_-]?key|token|secret|password|authorization)(["']?\s*[:=]\s*["']?)[^\s"'&,;]+/gi;
const BARE: RegExp[] = [/sk-[A-Za-z0-9_-]{8,}/g, /Bearer\s+[A-Za-z0-9._~+/=-]{6,}/gi];

export function secretValues(env: NodeJS.ProcessEnv = process.env): string[] {
  const values = new Set<string>();
  for (const [name, value] of Object.entries(env)) {
    if (value && value.length >= 8 && SENSITIVE_NAME.test(name)) values.add(value);
  }
  return [...values].sort((a, b) => b.length - a.length);
}

export function redact(text: string, extra: string[] = []): string {
  let out = text;
  for (const value of [...secretValues(), ...extra.filter((v) => v.length >= 4)]) {
    out = out.split(value).join("[redacted]");
  }
  for (const pattern of BARE) out = out.replace(pattern, "[redacted]");
  out = out.replace(KEY_VALUE, "$1$2[redacted]");
  return out;
}

export function errorMessage(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error);
  // eslint-disable-next-line no-control-regex
  const clean = raw.replace(/\u001b\[[0-9;]*m/g, "");
  const firstLine = clean.split("\n").find((l) => l.trim() !== "") ?? "unknown error";
  return redact(firstLine.trim());
}

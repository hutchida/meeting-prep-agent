export function formatDuration(ms: number): string {
  const s = Math.max(0, ms) / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = Math.floor(s / 60);
  return `${m} m ${Math.round(s - m * 60)} s`;
}

export const formatCost = (usd: number) => `$${usd.toFixed(4)}`;
export const formatCount = (n: number) => n.toLocaleString("en-US");

export function formatArgs(args: Record<string, string | number | boolean>, max = 80): string {
  const text = Object.entries(args)
    .map(([k, v]) => `${k}=${typeof v === "string" ? JSON.stringify(v) : String(v)}`)
    .join(", ");
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

export const AGENT_LABEL = {
  correspondence: "Correspondence",
  documents: "Documents",
  news: "News",
  attendees: "Attendees",
} as const;

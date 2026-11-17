import { CITATION_TOKEN_PATTERN, parseCitations, type Citation } from "@mpa/contract";

export type Segment = { kind: "text"; text: string } | { kind: "cite"; citation: Citation };

export const citeKey = (c: Citation) => `${c.type}:${c.id}`;

/** Split sentence text into plain text and inline `[type:id]` citation tokens. */
export function tokenize(text: string): Segment[] {
  const out: Segment[] = [];
  let last = 0;
  const tokens = parseCitations(text);
  let i = 0;
  for (const match of text.matchAll(new RegExp(CITATION_TOKEN_PATTERN, "g"))) {
    const at = match.index ?? 0;
    if (at > last) out.push({ kind: "text", text: text.slice(last, at) });
    out.push({ kind: "cite", citation: tokens[i++]! });
    last = at + match[0].length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}

/** Structured citations not already shown inline, de-duplicated, in order. */
export function trailingCitations(text: string, citations: readonly Citation[]): Citation[] {
  const inline = new Set(parseCitations(text).map(citeKey));
  const seen = new Set<string>();
  return citations.filter((c) => {
    const key = citeKey(c);
    if (inline.has(key) || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

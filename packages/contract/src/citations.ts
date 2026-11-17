import { z } from "zod";
import { type CitationType, ID_PREFIX, idOf } from "./common";

export const CitationEmail = z
  .strictObject({ type: z.literal("email"), id: idOf(ID_PREFIX.email) })
  .meta({ id: "CitationEmail" });
export const CitationChat = z
  .strictObject({ type: z.literal("chat"), id: idOf(ID_PREFIX.chat) })
  .meta({ id: "CitationChat" });
export const CitationDoc = z
  .strictObject({ type: z.literal("doc"), id: idOf(ID_PREFIX.doc) })
  .meta({ id: "CitationDoc" });
export const CitationNews = z
  .strictObject({ type: z.literal("news"), id: idOf(ID_PREFIX.news) })
  .meta({ id: "CitationNews" });
export const CitationContact = z
  .strictObject({ type: z.literal("contact"), id: idOf(ID_PREFIX.contact) })
  .meta({ id: "CitationContact" });
export const CitationCal = z
  .strictObject({ type: z.literal("cal"), id: idOf(ID_PREFIX.cal) })
  .meta({ id: "CitationCal" });

/** `{type, id}`; the id prefix must match the type (E/C/D/N/P/M). */
export const Citation = z
  .discriminatedUnion("type", [
    CitationEmail,
    CitationChat,
    CitationDoc,
    CitationNews,
    CitationContact,
    CitationCal,
  ])
  .meta({ id: "Citation" });
export type Citation = z.infer<typeof Citation>;

/** Matches one inline citation token such as `[email:E123]`; the id prefix must fit the type. */
export const CITATION_TOKEN_PATTERN =
  "\\[(?:email:E[0-9]{1,9}|chat:C[0-9]{1,9}|doc:D[0-9]{1,9}|news:N[0-9]{1,9}|contact:P[0-9]{1,9}|cal:M[0-9]{1,9})\\]";

/** Render a citation as the inline token `[type:id]`. Throws if the id does not fit the type. */
export function citationToken(citation: Citation): string {
  const parsed = Citation.parse(citation);
  return `[${parsed.type}:${parsed.id}]`;
}

/** All valid inline citation tokens in `text`, in order of appearance (duplicates kept). */
export function parseCitations(text: string): Citation[] {
  const out: Citation[] = [];
  for (const match of text.matchAll(new RegExp(CITATION_TOKEN_PATTERN, "g"))) {
    const [type, id] = match[0].slice(1, -1).split(":") as [CitationType, string];
    out.push({ type, id } as Citation);
  }
  return out;
}

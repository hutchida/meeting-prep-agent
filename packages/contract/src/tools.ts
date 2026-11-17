import { z } from "zod";
import { idOf } from "./common";
import { SourceItem } from "./items";

const hit = (type: "email" | "chat" | "doc" | "news" | "contact" | "cal", prefix: string, id: string) =>
  z
    .strictObject({
      type: z.literal(type),
      id: idOf(prefix),
      title: z.string().max(200),
      snippet: z.string().max(400),
      score: z.number().min(0),
    })
    .meta({ id });

export const SearchHitEmail = hit("email", "E", "SearchHitEmail");
export const SearchHitChat = hit("chat", "C", "SearchHitChat");
export const SearchHitDoc = hit("doc", "D", "SearchHitDoc");
export const SearchHitNews = hit("news", "N", "SearchHitNews");
export const SearchHitContact = hit("contact", "P", "SearchHitContact");
export const SearchHitCal = hit("cal", "M", "SearchHitCal");

/** Small projection returned by search tools. Full bodies come from the `get_*` tools. */
export const SearchHit = z
  .discriminatedUnion("type", [
    SearchHitEmail,
    SearchHitChat,
    SearchHitDoc,
    SearchHitNews,
    SearchHitContact,
    SearchHitCal,
  ])
  .meta({ id: "SearchHit" });
export type SearchHit = z.infer<typeof SearchHit>;

/**
 * What a tool hands back to the model. At most 10 items, each at most 4 KB of compact JSON
 * (enforced by `assertWithinLimit("tool_result", ...)`, not by the JSON Schema). Search tools return
 * `SearchHit`s; `get_*` tools return one full `SourceItem`, with the body truncated to fit the
 * per-item limit and `truncated` set when that happened.
 */
export const ToolResult = z
  .strictObject({
    items: z.array(z.union([SearchHit, SourceItem])).max(10),
    total_matches: z.number().int().min(0),
    truncated: z.boolean(),
  })
  .meta({ id: "ToolResult" });
export type ToolResult = z.infer<typeof ToolResult>;

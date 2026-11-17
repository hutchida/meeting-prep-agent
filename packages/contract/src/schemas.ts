import type { ZodType } from "zod";
import { BriefingPack, BriefingRequest, SubAgentOutput } from "./briefing";
import { Citation } from "./citations";
import { EvalResult } from "./evals";
import { AgentEvent } from "./events";
import { CalendarEvent, ChatMessage, Contact, Doc, Email, NewsItem, SourceItem } from "./items";
import { SearchHit, ToolResult } from "./tools";

/** Schemas exported to `schema/<Name>.json`. Fixture file names start with one of these names. */
export const SCHEMAS = {
  AgentEvent,
  BriefingPack,
  BriefingRequest,
  CalendarEvent,
  ChatMessage,
  Citation,
  Contact,
  Doc,
  Email,
  EvalResult,
  NewsItem,
  SearchHit,
  SourceItem,
  SubAgentOutput,
  ToolResult,
} satisfies Record<string, ZodType>;

export type SchemaName = keyof typeof SCHEMAS;

import { z } from "zod";
import { CalId, ChatId, ContactId, DocId, EmailId, IsoDateTime, NewsId } from "./common";

const EMAIL_ADDRESS = z.string().regex(/^[^@\s]+@[^@\s]+$/).max(200);

export const EMAIL_ORIGINS = ["synthetic", "enron"] as const;

export const Email = z
  .strictObject({
    type: z.literal("email"),
    id: EmailId,
    thread_id: z.string().min(1).max(80),
    sender: EMAIL_ADDRESS,
    to: z.array(EMAIL_ADDRESS).max(30),
    cc: z.array(EMAIL_ADDRESS).max(30),
    date: IsoDateTime,
    subject: z.string().max(300),
    body: z.string().max(6144),
    origin: z.enum(EMAIL_ORIGINS).optional(),
  })
  .meta({ id: "Email" });
export type Email = z.infer<typeof Email>;

export const ChatMessage = z
  .strictObject({
    type: z.literal("chat"),
    id: ChatId,
    channel: z.string().min(1).max(80),
    thread_id: z.string().min(1).max(80).optional(),
    author: z.string().min(1).max(100),
    ts: IsoDateTime,
    text: z.string().max(4000),
  })
  .meta({ id: "ChatMessage" });
export type ChatMessage = z.infer<typeof ChatMessage>;

export const DOC_KINDS = ["proposal", "notes", "contract", "other"] as const;

export const Doc = z
  .strictObject({
    type: z.literal("doc"),
    id: DocId,
    title: z.string().min(1).max(200),
    kind: z.enum(DOC_KINDS),
    author: z.string().min(1).max(100),
    date: IsoDateTime,
    body: z.string().max(12000),
  })
  .meta({ id: "Doc" });
export type Doc = z.infer<typeof Doc>;

export const CalendarEvent = z
  .strictObject({
    type: z.literal("cal"),
    id: CalId,
    title: z.string().min(1).max(200),
    start: IsoDateTime,
    end: IsoDateTime,
    attendees: z.array(ContactId).max(30),
    location: z.string().max(200),
    description: z.string().max(2000),
  })
  .meta({ id: "CalendarEvent" });
export type CalendarEvent = z.infer<typeof CalendarEvent>;

export const Contact = z
  .strictObject({
    type: z.literal("contact"),
    id: ContactId,
    name: z.string().min(1).max(100),
    email: EMAIL_ADDRESS,
    organization: z.string().min(1).max(100),
    role: z.string().max(100),
    notes: z.string().max(1000),
    is_user: z.boolean(),
  })
  .meta({ id: "Contact" });
export type Contact = z.infer<typeof Contact>;

export const NewsItem = z
  .strictObject({
    type: z.literal("news"),
    id: NewsId,
    title: z.string().min(1).max(300),
    source: z.string().min(1).max(100),
    published: IsoDateTime,
    url: z.string().regex(/^https:\/\/example\.test\/[^\s]*$/).max(300),
    body: z.string().max(4000),
    about: z.string().max(100).optional(),
  })
  .meta({ id: "NewsItem" });
export type NewsItem = z.infer<typeof NewsItem>;

/** Response body of `GET /sources/{type}/{id}`. */
export const SourceItem = z
  .discriminatedUnion("type", [Email, ChatMessage, Doc, CalendarEvent, Contact, NewsItem])
  .meta({ id: "SourceItem" });
export type SourceItem = z.infer<typeof SourceItem>;

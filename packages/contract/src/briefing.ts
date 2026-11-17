import { z } from "zod";
import { CalId, Gap, IsoDateTime, Stats, AGENT_NAMES } from "./common";
import { Citation } from "./citations";

export const FAIL_SOURCES = ["news", "email", "docs", "all"] as const;

export const BriefingRequest = z
  .strictObject({
    message: z.string().min(1).max(2000),
    fail_source: z.enum(FAIL_SOURCES).optional(),
  })
  .meta({ id: "BriefingRequest", description: "Body of POST /briefings." });
export type BriefingRequest = z.infer<typeof BriefingRequest>;

const sentenceText = z.string().min(1).max(600);

/** A factual sentence: at least one citation is mandatory. */
export const FactSentence = z
  .strictObject({
    text: sentenceText,
    citations: z.array(Citation).min(1).max(8),
    kind: z.literal("fact").optional(),
  })
  .meta({ id: "FactSentence" });

/** An explicit note such as "No recent news found"; the only sentence allowed without citations. */
export const NoteSentence = z
  .strictObject({
    text: sentenceText,
    citations: z.array(Citation).max(8),
    kind: z.literal("note"),
  })
  .meta({ id: "NoteSentence" });

export const Sentence = z.union([FactSentence, NoteSentence]).meta({ id: "Sentence" });
export type Sentence = z.infer<typeof Sentence>;

export const SECTION_IDS = [
  "meeting_at_a_glance",
  "client_snapshot",
  "recent_news",
  "where_we_left_off",
  "open_items",
  "attendees",
  "talking_points_and_risks",
] as const;
export const SectionId = z.enum(SECTION_IDS);
export type SectionId = z.infer<typeof SectionId>;

const section = <const I extends SectionId>(id: I, defId: string) =>
  z
    .strictObject({
      id: z.literal(id),
      title: z.string().min(1).max(120),
      sentences: z.array(Sentence).max(16),
      empty: z.boolean(),
    })
    .meta({ id: defId });

export const MeetingAtAGlanceSection = section("meeting_at_a_glance", "MeetingAtAGlanceSection");
export const ClientSnapshotSection = section("client_snapshot", "ClientSnapshotSection");
export const RecentNewsSection = section("recent_news", "RecentNewsSection");
export const WhereWeLeftOffSection = section("where_we_left_off", "WhereWeLeftOffSection");
export const OpenItemsSection = section("open_items", "OpenItemsSection");
export const AttendeesSection = section("attendees", "AttendeesSection");
export const TalkingPointsAndRisksSection = section(
  "talking_points_and_risks",
  "TalkingPointsAndRisksSection",
);

/** Any one section (used by streamed drafts, where only some sections exist yet). */
export const BriefingSection = z
  .union([
    MeetingAtAGlanceSection,
    ClientSnapshotSection,
    RecentNewsSection,
    WhereWeLeftOffSection,
    OpenItemsSection,
    AttendeesSection,
    TalkingPointsAndRisksSection,
  ])
  .meta({ id: "BriefingSection" });
export type BriefingSection = z.infer<typeof BriefingSection>;

export const MeetingRef = z
  .strictObject({
    cal_id: CalId,
    title: z.string().min(1).max(200),
    start: IsoDateTime,
  })
  .meta({ id: "MeetingRef" });

export const VerifierCounts = z
  .strictObject({
    sentences_total: z.number().int().min(0),
    sentences_kept: z.number().int().min(0),
    sentences_dropped: z.number().int().min(0),
  })
  .meta({ id: "VerifierCounts" });
export type VerifierCounts = z.infer<typeof VerifierCounts>;

/** The 7 sections always appear in this fixed order with these fixed ids. */
export const BriefingPack = z
  .strictObject({
    run_id: z.string().min(1).max(64),
    client: z.string().min(1).max(100),
    meeting: MeetingRef,
    partial: z.boolean(),
    gaps: z.array(Gap).max(12),
    verifier: VerifierCounts,
    stats: Stats,
    model: z.string().min(1).max(100),
    sections: z.tuple([
      MeetingAtAGlanceSection,
      ClientSnapshotSection,
      RecentNewsSection,
      WhereWeLeftOffSection,
      OpenItemsSection,
      AttendeesSection,
      TalkingPointsAndRisksSection,
    ]),
  })
  .meta({ id: "BriefingPack" });
export type BriefingPack = z.infer<typeof BriefingPack>;

export const SubAgentOutput = z
  .strictObject({
    agent: z.enum(AGENT_NAMES),
    findings: z.array(Sentence).max(30),
    gaps: z.array(Gap).max(12),
  })
  .meta({ id: "SubAgentOutput" });
export type SubAgentOutput = z.infer<typeof SubAgentOutput>;

export const Finding = Sentence;
export type Finding = Sentence;

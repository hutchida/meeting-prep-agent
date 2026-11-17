import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { AgentEvent, BriefingPack, SourceItem } from "@mpa/contract";

const FIXTURES = resolve(process.cwd(), "../../packages/contract/fixtures") + "/";

export const readJson = (rel: string): unknown => JSON.parse(readFileSync(FIXTURES + rel, "utf8"));

export type RunName = "brightmoor.normal" | "brightmoor.news_down" | "halden.budget_hit";

export function loadRun(name: RunName): { events: AgentEvent[]; pack: BriefingPack } {
  return {
    events: (readJson(`runs/run.${name}.events.json`) as unknown[]).map((e) => AgentEvent.parse(e)),
    pack: BriefingPack.parse(readJson(`runs/run.${name}.pack.json`)),
  };
}

export const loadSource = (name: string) => SourceItem.parse(readJson(`SourceItem.${name}.json`));

export const sseFrame = (event: AgentEvent) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;

export function sseText(events: readonly AgentEvent[]): string {
  return `: stream-open\n\n${events.map(sseFrame).join("")}`;
}

export function streamOf(chunks: (string | Uint8Array)[], opts: { hold?: boolean } = {}) {
  const enc = new TextEncoder();
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      ctrl = c;
      for (const chunk of chunks) c.enqueue(typeof chunk === "string" ? enc.encode(chunk) : chunk);
      if (!opts.hold) c.close();
    },
  });
  return { stream, push: (s: string) => ctrl.enqueue(enc.encode(s)), close: () => ctrl.close(), error: (e: unknown) => ctrl.error(e) };
}

export function sseResponse(events: readonly AgentEvent[], status = 200): Response {
  return new Response(streamOf([sseText(events)]).stream, {
    status,
    headers: { "Content-Type": "text/event-stream" },
  });
}

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

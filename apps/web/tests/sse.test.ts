import { describe, expect, it } from "vitest";
import { SseParser, readSse } from "@/lib/sse";
import { streamOf } from "./helpers";

const TEXT =
  ': stream-open\n\nevent: plan\ndata: {"a":"£48,000 — café ☕"}\n\n: keep-alive\n\nevent: run_done\ndata: {"b":2}\n\n';
const EXPECTED = [
  { event: "plan", data: '{"a":"£48,000 — café ☕"}' },
  { event: "run_done", data: '{"b":2}' },
];

describe("SseParser", () => {
  it("parses frames and ignores comments", () => {
    expect(new SseParser().feed(TEXT)).toEqual(EXPECTED);
  });

  it("is stable at every byte split, including inside multi-byte UTF-8", () => {
    const bytes = new TextEncoder().encode(TEXT);
    for (let cut = 1; cut < bytes.length; cut++) {
      const p = new SseParser();
      const frames = [...p.feed(bytes.slice(0, cut)), ...p.feed(bytes.slice(cut)), ...p.end()];
      expect(frames).toEqual(EXPECTED);
    }
  });

  it("handles one byte at a time", () => {
    const p = new SseParser();
    const frames = [...new TextEncoder().encode(TEXT)].flatMap((b) => p.feed(new Uint8Array([b])));
    expect(frames).toEqual(EXPECTED);
  });

  it("accepts CRLF line endings, including a CR/LF split across chunks", () => {
    const p = new SseParser();
    const frames = [
      ...p.feed("event: plan\r\ndata: 1\r"),
      ...p.feed("\n\r\nevent: x\r\ndata: 2\r\n\r\n"),
    ];
    expect(frames).toEqual([
      { event: "plan", data: "1" },
      { event: "x", data: "2" },
    ]);
  });

  it("joins multi-line data and defaults the event name", () => {
    expect(new SseParser().feed("data: a\ndata: b\n\n")).toEqual([{ event: "message", data: "a\nb" }]);
  });

  it("drops frames without data and holds partial frames until complete", () => {
    const p = new SseParser();
    expect(p.feed("event: plan\n\n")).toEqual([]);
    expect(p.feed("event: plan\ndata: {")).toEqual([]);
    expect(p.feed('}\n\n')).toEqual([{ event: "plan", data: "{}" }]);
  });

  it("flushes a final unterminated frame on end()", () => {
    const p = new SseParser();
    p.feed("event: plan\ndata: 1");
    expect(p.end()).toEqual([{ event: "plan", data: "1" }]);
  });
});

describe("readSse", () => {
  it("reads frames from a ReadableStream split into tiny chunks", async () => {
    const bytes = new TextEncoder().encode(TEXT);
    const chunks = Array.from({ length: Math.ceil(bytes.length / 3) }, (_, i) =>
      bytes.slice(i * 3, i * 3 + 3),
    );
    const out = [];
    for await (const f of readSse(streamOf(chunks).stream)) out.push(f);
    expect(out).toEqual(EXPECTED);
  });
});

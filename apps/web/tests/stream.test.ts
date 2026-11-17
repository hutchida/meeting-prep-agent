import { describe, expect, it, vi } from "vitest";
import type { RunAction } from "@/lib/run";
import { streamBriefing } from "@/lib/stream";
import { json, loadRun, sseResponse, sseText, streamOf } from "./helpers";

const run = async (fetchImpl: typeof fetch, over: { failSource?: "news"; signal?: AbortSignal } = {}) => {
  const actions: RunAction[] = [];
  await streamBriefing({
    apiUrl: "http://api.test",
    message: "Prep me",
    failSource: over.failSource,
    signal: over.signal ?? new AbortController().signal,
    dispatch: (a) => actions.push(a),
    fetchImpl,
  });
  return actions;
};

describe("streamBriefing", () => {
  it("posts the request body and dispatches every valid event, then stream_end", async () => {
    const { events } = loadRun("brightmoor.normal");
    const fetchImpl = vi.fn(async () => sseResponse(events));
    const actions = await run(fetchImpl as unknown as typeof fetch, { failSource: "news" });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://api.test/briefings");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ message: "Prep me", fail_source: "news" });
    expect(actions.filter((a) => a.type === "event")).toHaveLength(events.length);
    expect(actions.at(-1)).toEqual({ type: "stream_end" });
  });

  it("omits fail_source when the outage toggle is off", async () => {
    const fetchImpl = vi.fn(async () => sseResponse([]));
    await run(fetchImpl as unknown as typeof fetch);
    const init = (fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(JSON.parse(init.body as string)).toEqual({ message: "Prep me" });
  });

  it("skips malformed and schema-invalid events safely", async () => {
    const { events } = loadRun("brightmoor.normal");
    const text =
      `event: plan\ndata: {not json\n\n` +
      `event: plan\ndata: ${JSON.stringify({ ...events[1]!, extra: 1 })}\n\n` +
      `event: made_up\ndata: ${JSON.stringify({ type: "made_up" })}\n\n` +
      sseText([events[0]!]);
    const actions = await run((async () => new Response(streamOf([text]).stream)) as typeof fetch);
    expect(actions.map((a) => a.type)).toEqual(["skipped", "skipped", "skipped", "event", "stream_end"]);
  });

  it("reports an unreachable API", async () => {
    const actions = await run((async () => {
      throw new TypeError("fetch failed");
    }) as typeof fetch);
    expect(actions).toEqual([{ type: "failed", kind: "unreachable", detail: expect.any(String) }]);
  });

  it("reports HTTP errors", async () => {
    const actions = await run((async () => json({ error: "x" }, 503)) as typeof fetch);
    expect(actions).toEqual([{ type: "failed", kind: "http", detail: expect.stringContaining("503") }]);
  });

  it("dispatches stopped when aborted mid-stream", async () => {
    const { events } = loadRun("brightmoor.normal");
    const ctrl = new AbortController();
    const held = streamOf([sseText(events.slice(0, 2))], { hold: true });
    const fetchImpl = (async (_u: string, init: RequestInit) => {
      init.signal?.addEventListener("abort", () =>
        held.error(new DOMException("aborted", "AbortError")),
      );
      return new Response(held.stream);
    }) as unknown as typeof fetch;
    const pending = run(fetchImpl, { signal: ctrl.signal });
    await new Promise((r) => setTimeout(r, 20));
    ctrl.abort();
    const actions = await pending;
    expect(actions.at(-1)).toEqual({ type: "stopped" });
  });
});

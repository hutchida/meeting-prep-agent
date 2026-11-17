export interface SseFrame {
  event: string;
  data: string;
}

/** Incremental `text/event-stream` parser. Feed raw bytes (or strings); frames come back whole. */
export class SseParser {
  private readonly decoder = new TextDecoder("utf-8");
  private buffer = "";

  feed(chunk: Uint8Array | string): SseFrame[] {
    this.buffer +=
      typeof chunk === "string" ? chunk : this.decoder.decode(chunk, { stream: true });
    this.buffer = this.buffer.replace(/\r\n?/g, "\n");
    const frames: SseFrame[] = [];
    let at: number;
    while ((at = this.buffer.indexOf("\n\n")) >= 0) {
      const raw = this.buffer.slice(0, at);
      this.buffer = this.buffer.slice(at + 2);
      const frame = parseFrame(raw);
      if (frame) frames.push(frame);
    }
    return frames;
  }

  /** Flush a final unterminated frame (only meaningful when the stream closed cleanly). */
  end(): SseFrame[] {
    this.buffer += this.decoder.decode();
    const rest = this.buffer.replace(/\r\n?/g, "\n").trim() === "" ? null : parseFrame(this.buffer);
    this.buffer = "";
    return rest ? [rest] : [];
  }
}

function parseFrame(raw: string): SseFrame | null {
  let event = "message";
  const data: string[] = [];
  for (const line of raw.split("\n")) {
    if (line === "" || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length === 0 ? null : { event, data: data.join("\n") };
}

export async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseFrame> {
  const reader = body.getReader();
  const parser = new SseParser();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      yield* parser.feed(value);
    }
    yield* parser.end();
  } finally {
    reader.releaseLock();
  }
}

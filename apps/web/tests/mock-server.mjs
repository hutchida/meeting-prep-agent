// Manual-check mock of the API (never used by pnpm check): node tests/mock-server.mjs [port]
// Replays contract run fixtures as SSE. "news outage" -> news_down run, "Halden" -> budget_hit run.
import { readFileSync, existsSync } from "node:fs";
import { createServer } from "node:http";
import { resolve } from "node:path";

const FIXTURES = resolve(import.meta.dirname, "../../../packages/contract/fixtures");
const PORT = Number(process.argv[2] ?? process.env.MOCK_PORT ?? 8000);
const DELAY_MS = Number(process.env.MOCK_DELAY_MS ?? 250);
const load = (rel) => JSON.parse(readFileSync(`${FIXTURES}/${rel}`, "utf8"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const cors = {
  "Access-Control-Allow-Origin": "http://localhost:3000",
  "Access-Control-Allow-Headers": "content-type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", "http://x");
  if (req.method === "OPTIONS") return res.writeHead(204, cors).end();
  if (req.method === "GET" && url.pathname === "/health") {
    return res.writeHead(200, { ...cors, "Content-Type": "application/json" }).end('{"status":"ok"}');
  }
  const src = url.pathname.match(/^\/sources\/([a-z]+)\/([A-Z0-9]+)$/);
  if (req.method === "GET" && src) {
    const file = { email: "Email.basic", chat: "ChatMessage.basic", doc: "Doc.basic", news: "NewsItem.basic", contact: "Contact.basic", cal: "CalendarEvent.basic" }[src[1]];
    if (!file || !existsSync(`${FIXTURES}/${file}.json`)) return res.writeHead(404, cors).end('{"error":"not_found"}');
    await sleep(300);
    return res.writeHead(200, { ...cors, "Content-Type": "application/json" }).end(JSON.stringify({ ...load(`${file}.json`), id: src[2] }));
  }
  if (req.method === "POST" && url.pathname === "/briefings") {
    let raw = "";
    for await (const c of req) raw += c;
    const body = JSON.parse(raw || "{}");
    const name = body.fail_source === "news" ? "brightmoor.news_down" : /halden/i.test(body.message ?? "") ? "halden.budget_hit" : "brightmoor.normal";
    const events = load(`runs/run.${name}.events.json`);
    res.writeHead(200, { ...cors, "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
    res.write(": stream-open\n\n");
    let closed = false;
    res.on("close", () => (closed = true));
    for (const e of events) {
      await sleep(DELAY_MS);
      if (closed) return;
      res.write(`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`);
    }
    return res.end();
  }
  res.writeHead(404, cors).end();
}).listen(PORT, "127.0.0.1", () => console.log(`mock API on http://127.0.0.1:${PORT}`));

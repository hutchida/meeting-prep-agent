import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

export interface FixtureOptions {
  briefingDelayMs?: number;
}

export interface FixtureServer {
  url: string;
  close: () => Promise<void>;
}

const SECTIONS = [
  "meeting_at_a_glance",
  "client_snapshot",
  "recent_news",
  "where_we_left_off",
  "open_items",
  "attendees",
  "talking_points_and_risks",
];

const PAGE = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Capture fixture</title>
<style>
body{font-family:system-ui,sans-serif;margin:24px;background:#fafafa;color:#222}
button{padding:8px 12px;margin:4px;border:1px solid #888;border-radius:6px;background:#fff;cursor:pointer}
input[type=text]{padding:8px;width:420px}
#timeline{margin:16px 0;padding:8px;border:1px solid #ccd;background:#fff;min-height:40px}
.row{padding:2px 6px;border-bottom:1px solid #eee;font-size:14px}
.row[data-type=subagent_failed]{color:#a00}.row[data-type=retry]{color:#b60}
section{margin:8px 0;padding:8px;border:1px solid #ddd;background:#fff}
.cite{color:#06c;cursor:pointer;margin-left:4px}
#source-panel{position:fixed;right:0;top:0;width:320px;height:100%;background:#fff;border-left:2px solid #444;padding:16px}
</style></head><body>
<h1>Fixture</h1>
<div id="starters">
  <button data-testid="starter-halden">Prep me for my meeting with Halden</button>
  <button data-testid="starter-brightmoor">Prep me for my meeting with Brightmoor on Thursday</button>
  <button data-testid="starter-kettle">Prep me for my meeting with Kettle</button>
</div>
<label><input type="checkbox" data-testid="toggle-news-outage"> Simulate news outage</label>
<div><input type="text" data-testid="chat-input" placeholder="Ask"><button data-testid="chat-send">Send</button></div>
<div id="timeline-host"></div><div id="briefing-host"></div><div id="stats-host"></div><div id="panel-host"></div>
<script>
const SECTIONS = ${JSON.stringify(SECTIONS)};
const DELAY = Number(new URLSearchParams(location.search).get("delay") || window.__BRIEFING_DELAY || 0);
const AGENTS = ["email", "chat", "docs", "calendar", "news"];
let timers = [];
const $ = (id) => document.querySelector('[data-testid="' + id + '"]');
function at(ms, fn) { timers.push(setTimeout(fn, ms)); }
function row(type, agent) {
  const el = document.createElement("div");
  el.className = "row"; el.setAttribute("data-testid", "timeline-event"); el.setAttribute("data-type", type);
  if (agent) el.setAttribute("data-agent", agent);
  el.textContent = type + (agent ? " " + agent : "");
  document.getElementById("tl").appendChild(el);
}
function run(prompt) {
  timers.forEach(clearTimeout); timers = [];
  const outage = $("toggle-news-outage").checked;
  document.getElementById("timeline-host").innerHTML = '<div id="tl" data-testid="step-timeline"></div>';
  document.getElementById("briefing-host").innerHTML = "";
  document.getElementById("stats-host").innerHTML = "";
  at(50, () => row("plan"));
  AGENTS.forEach((a, i) => at(100 + i * 30, () => row("subagent_started", a)));
  if (outage) {
    at(300, () => row("subagent_failed", "news"));
    at(350, () => row("retry", "news"));
    at(400, () => row("subagent_failed", "news"));
  }
  at(500 + DELAY, () => {
    const sections = SECTIONS.map((s) => {
      const text = s === "recent_news" && outage
        ? "News could not be reached, so this section is unavailable."
        : "Summary for " + s + " <span class='cite' data-testid='citation' data-cite='email:E123'>[1]</span>";
      return '<section data-testid="section-' + s + '">' + text + "</section>";
    }).join("");
    document.getElementById("briefing-host").innerHTML = '<div data-testid="briefing">' + sections + "</div>";
    document.getElementById("stats-host").innerHTML = '<div data-testid="run-stats">5 steps, 1.2s</div>';
  });
}
function send() { const v = $("chat-input").value; if (v) run(v); }
document.addEventListener("click", (ev) => {
  const t = ev.target.closest("[data-testid]");
  if (!t) return;
  const id = t.getAttribute("data-testid");
  if (id.startsWith("starter-")) { $("chat-input").value = t.textContent; run(t.textContent); }
  else if (id === "chat-send") send();
  else if (id === "citation") {
    document.getElementById("panel-host").innerHTML =
      '<div data-testid="source-panel"><button data-testid="source-panel-close">Close</button><p>Email E123: Re: Brightmoor renewal</p></div>';
  } else if (id === "source-panel-close") document.getElementById("panel-host").innerHTML = "";
});
$("chat-input").addEventListener("keydown", (ev) => { if (ev.key === "Enter") send(); });
</script></body></html>`;

export async function startFixtureServer(options: FixtureOptions = {}): Promise<FixtureServer> {
  const html = PAGE.replace("</head>", `<script>window.__BRIEFING_DELAY=${Number(options.briefingDelayMs ?? 0)}</script></head>`);
  const server: Server = createServer((req, res) => {
    if (req.url === "/" || req.url?.startsWith("/?")) {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(html);
    } else {
      res.writeHead(404).end("not found");
    }
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}`,
    close: () =>
      new Promise<void>((resolve) => {
        server.closeAllConnections();
        server.close(() => resolve());
      }),
  };
}

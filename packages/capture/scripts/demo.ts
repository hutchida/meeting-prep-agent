import {
  click,
  expectCount,
  expectDistinctAttr,
  expectMarkWithin,
  expectText,
  expectVisible,
  fill,
  goto,
  mark,
  note,
  screenshot,
  toggle,
  waitFor,
  waitForNoTestId,
  waitForTestId,
  type Step,
} from "../src/steps";
import type { ScriptContext, ScriptDefinition } from "../src/script";

export const SECTION_IDS = [
  "meeting_at_a_glance",
  "client_snapshot",
  "recent_news",
  "where_we_left_off",
  "open_items",
  "attendees",
  "talking_points_and_risks",
] as const;

const PROMPT = "Prep me for my meeting with Brightmoor on Thursday";
const timelineRows = (type: string) => ({
  css: `[data-testid="timeline-event"][data-type="${type}"]`,
});
const section = (id: string) => ({ testId: `section-${id}`, nth: -1 });

export default function demo(ctx: ScriptContext): ScriptDefinition {
  const maxBriefingMs = ctx.maxBriefingMs ?? (ctx.live ? 90_000 : 10_000);
  const waitMs = maxBriefingMs + 5_000;
  const secondRunMs = Math.max(30_000, maxBriefingMs * 2);

  const steps: Step[] = [
    goto("/", { name: "1. open home page" }),
    expectCount({ css: '[data-testid^="starter-"]' }, { exactly: 3 }, { name: "1. three starter prompts" }),
    expectVisible({ testId: "starter-brightmoor" }),
    screenshot("home"),

    click({ testId: "starter-brightmoor" }, { name: "2. click Brightmoor starter" }),
    mark("prompt-sent"),
    waitForTestId("step-timeline", { name: "2. step timeline appears", timeoutMs: waitMs }),
    waitFor(timelineRows("plan"), { name: "2. plan event", timeoutMs: waitMs }),
    expectDistinctAttr(
      timelineRows("subagent_started"),
      "data-agent",
      4,
      { name: "2. at least 4 distinct sub-agents started", timeoutMs: waitMs },
    ),
    screenshot("timeline"),

    waitForTestId("briefing", { name: "3. briefing appears", timeoutMs: waitMs }),
    ...SECTION_IDS.map((id) =>
      waitForTestId(`section-${id}`, { name: `3. section ${id}`, timeoutMs: waitMs }),
    ),
    mark("briefing-ready"),
    expectMarkWithin("briefing-ready", "prompt-sent", maxBriefingMs, {
      name: `3. briefing within ${maxBriefingMs}ms`,
    }),
    note(`briefing limit ${maxBriefingMs}ms`),
    screenshot("briefing"),

    click({ testId: "citation", nth: 0 }, { name: "4. click first citation" }),
    expectVisible({ testId: "source-panel" }, { name: "4. source panel visible" }),
    expectText({ testId: "source-panel" }, /\S/, { name: "4. source panel has text" }),
    screenshot("source-panel"),
    click({ testId: "source-panel-close" }, { name: "4. close source panel" }),
    waitForNoTestId("source-panel", { name: "4. source panel closed" }),

    toggle({ testId: "toggle-news-outage" }, true, { name: "5. simulate news outage" }),
    fill({ testId: "chat-input" }, PROMPT, { name: "5. type the same prompt" }),
    click({ testId: "chat-send" }, { name: "5. send prompt again" }),
    expectCount(timelineRows("retry"), { atLeast: 1 }, {
      name: "5. retry events appear",
      timeoutMs: secondRunMs,
    }),
    expectCount(timelineRows("subagent_failed"), { atLeast: 1 }, {
      name: "5. subagent_failed events appear",
      timeoutMs: secondRunMs,
    }),
    screenshot("outage-timeline"),
    expectText(section("recent_news"), "could not be reached", {
      name: "5. recent news explains the outage",
      timeoutMs: secondRunMs,
    }),
    ...SECTION_IDS.filter((id) => id !== "recent_news").map((id) =>
      expectVisible(section(id), { name: `5. section ${id} still rendered`, timeoutMs: secondRunMs }),
    ),
    screenshot("outage-briefing"),
  ];

  return {
    name: "demo",
    steps,
    totalTimeoutMs: ctx.live ? 300_000 : 60_000,
  };
}

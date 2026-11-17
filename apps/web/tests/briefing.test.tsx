import { fireEvent, render, screen, within } from "@testing-library/react";
import { SECTION_IDS, type BriefingPack } from "@mpa/contract";
import { describe, expect, it, vi } from "vitest";
import { Briefing } from "@/components/Briefing";
import { StepTimeline } from "@/components/StepTimeline";
import { deriveView } from "@/lib/run";
import { loadRun, readJson } from "./helpers";

const renderBriefing = (name: Parameters<typeof loadRun>[0], onOpenSource = vi.fn()) => {
  const { events } = loadRun(name);
  const view = deriveView(events, true);
  render(<Briefing view={view} status="done" activeCite={null} onOpenSource={onOpenSource} />);
  return { view, onOpenSource };
};

describe("Briefing", () => {
  it("renders the 7 sections in order with titles", () => {
    const { view } = renderBriefing("brightmoor.normal");
    const rendered = within(screen.getByTestId("briefing"))
      .getAllByTestId(/^section-/)
      .map((el) => el.getAttribute("data-testid"));
    expect(rendered).toEqual(SECTION_IDS.map((id) => `section-${id}`));
    for (const s of view.sections) {
      expect(within(screen.getByTestId(`section-${s.id}`)).getByRole("heading").textContent).toBe(s.title);
    }
    expect(screen.queryByTestId("partial-banner")).toBeNull();
  });

  it("renders a citation chip per structured citation and opens it on click", () => {
    const { view, onOpenSource } = renderBriefing("brightmoor.normal");
    const first = view.sections[0]!.sentences[0]!.citations[0]!;
    const chips = screen.getAllByTestId("citation");
    const chip = chips.find((c) => c.getAttribute("data-cite") === `${first.type}:${first.id}`)!;
    fireEvent.click(chip);
    expect(onOpenSource).toHaveBeenCalledWith(first);
  });

  it("shows the partial banner with gaps when news is down", () => {
    renderBriefing("brightmoor.news_down");
    const banner = screen.getByTestId("partial-banner");
    expect(banner.textContent).toContain("Partial briefing");
    expect(within(banner).getAllByTestId("gap").length).toBeGreaterThan(0);
    expect(banner.textContent).toContain("news");
  });

  it("shows note sentences of empty sections plainly", () => {
    const pack = readJson("BriefingPack.empty_news.json") as BriefingPack;
    const news = pack.sections[2];
    expect(news.empty).toBe(true);
    const { events } = loadRun("brightmoor.normal");
    const view = deriveView(events, true);
    view.sections = view.sections.map((s) => (s.id === "recent_news" ? news : s));
    render(<Briefing view={view} status="done" activeCite={null} onOpenSource={vi.fn()} />);
    const text = screen.getByTestId("section-recent_news").textContent;
    expect(text).toContain(news.sentences[0]!.text);
  });

  it("renders inline citation tokens as chips and never raw HTML", () => {
    const { events } = loadRun("brightmoor.normal");
    const view = deriveView(events, true);
    view.sections = [
      {
        id: "meeting_at_a_glance",
        title: "Meeting at a glance",
        empty: false,
        sentences: [
          {
            text: 'Hello **bold** <img src=x onerror="alert(1)"><script>alert(2)</script> [email:E5] and [x](https://evil.test)',
            citations: [
              { type: "email", id: "E5" },
              { type: "doc", id: "D1" },
            ],
          },
        ],
      },
    ];
    render(<Briefing view={view} status="done" activeCite={null} onOpenSource={vi.fn()} />);
    const section = screen.getByTestId("section-meeting_at_a_glance");
    expect(section.querySelector("img, script, a")).toBeNull();
    expect(section.querySelector("strong")?.textContent).toBe("bold");
    expect(within(section).getAllByTestId("citation").map((c) => c.getAttribute("data-cite"))).toEqual([
      "email:E5",
      "doc:D1",
    ]);
  });

  it("shows skeletons for pending sections while writing and nothing before", () => {
    const { events } = loadRun("brightmoor.normal");
    const at = events.findIndex((e) => e.type === "draft");
    const view = deriveView(events.slice(0, at + 2), false);
    const { unmount } = render(
      <Briefing view={view} status="running" activeCite={null} onOpenSource={vi.fn()} />,
    );
    expect(screen.getAllByTestId(/^section-skeleton-/)).toHaveLength(5);
    expect(screen.getAllByTestId(/^section-(?!skeleton)/)).toHaveLength(2);
    unmount();
    const early = deriveView(events.slice(0, 4), false);
    const { container } = render(
      <Briefing view={early} status="running" activeCite={null} onOpenSource={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });
});

describe("StepTimeline", () => {
  it("renders every event with type and agent attributes inside the lanes", () => {
    const { events } = loadRun("brightmoor.news_down");
    const view = deriveView(events.slice(0, 24), false);
    render(<StepTimeline view={view} status="running" />);
    const rows = screen.getAllByTestId("timeline-event");
    expect(rows).toHaveLength(24);
    expect(screen.getByTestId("step-timeline")).toBeTruthy();
    expect(rows.filter((r) => r.getAttribute("data-type") === "retry").every((r) => r.getAttribute("data-agent"))).toBe(true);
    expect(rows[0]!.getAttribute("data-agent")).toBeNull();
    expect(screen.getAllByTestId("agent-lane")).toHaveLength(4);
    const news = screen.getAllByTestId("agent-lane").find((l) => l.getAttribute("data-agent") === "news")!;
    expect(news.getAttribute("data-status")).toBe("failed");
    const failedRow = within(news).getAllByTestId("timeline-event").find((r) => r.getAttribute("data-type") === "subagent_failed")!;
    expect(failedRow.className).toContain("text-red");
    const retry = rows.find((r) => r.getAttribute("data-type") === "retry")!;
    expect(retry.className).toContain("text-amber");
  });

  it("shows tool name, args, item count and ids, and the verifier summary", () => {
    const { events } = loadRun("brightmoor.normal");
    render(<StepTimeline view={deriveView(events, true)} status="running" />);
    const result = screen.getAllByTestId("timeline-event").find((r) => r.getAttribute("data-type") === "tool_result")!;
    expect(result.textContent).toMatch(/\d+ items?/);
    const verifier = screen.getAllByTestId("timeline-event").find((r) => r.getAttribute("data-type") === "verifier_result")!;
    expect(verifier.textContent).toMatch(/kept \d+ of \d+ sentences, dropped \d+/);
    expect(screen.getByText(/^Plan$/)).toBeTruthy();
  });

  it("collapses once done and can be toggled", () => {
    const { events } = loadRun("brightmoor.normal");
    const view = deriveView(events, true);
    render(<StepTimeline view={view} status="done" />);
    expect(screen.queryAllByTestId("timeline-event")).toHaveLength(0);
    fireEvent.click(screen.getByTestId("timeline-toggle"));
    expect(screen.getAllByTestId("timeline-event")).toHaveLength(events.length);
    expect(screen.getByTestId("timeline-toggle").getAttribute("aria-expanded")).toBe("true");
  });
});

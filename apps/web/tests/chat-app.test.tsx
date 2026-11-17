import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatApp } from "@/components/ChatApp";
import { json, loadRun, loadSource, sseResponse, sseText, streamOf } from "./helpers";

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>;
let handler: Handler;
const fetchMock = vi.fn((url: string, init?: RequestInit) => Promise.resolve(handler(url, init)));

beforeEach(() => {
  fetchMock.mockClear();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const bodyOf = (call: number) => JSON.parse((fetchMock.mock.calls[call]![1] as RequestInit).body as string);

describe("ChatApp", () => {
  it("shows three starters with the exact prompts and the controls", () => {
    render(<ChatApp />);
    expect(screen.getByTestId("starter-halden").textContent).toBe("Prep me for my meeting with Halden Pay on Wednesday");
    expect(screen.getByTestId("starter-brightmoor").textContent).toBe("Prep me for my meeting with Brightmoor on Thursday");
    expect(screen.getByTestId("starter-kettle").textContent).toBe("Prep me for my meeting with Kettle & Crumb on Friday");
    expect(screen.getByTestId("chat-input")).toBeTruthy();
    expect(screen.getByTestId("toggle-news-outage")).toBeTruthy();
    expect((screen.getByTestId("chat-send") as HTMLButtonElement).disabled).toBe(true);
  });

  it("runs a starter end to end: timeline, briefing, citations, stats, source panel", async () => {
    const { events, pack } = loadRun("brightmoor.normal");
    const email = loadSource("email");
    handler = (url) => (url.endsWith("/briefings") ? sseResponse(events) : json(email));
    render(<ChatApp />);
    fireEvent.click(screen.getByTestId("starter-brightmoor"));
    await waitFor(() => expect(screen.getByTestId("assistant-card").getAttribute("data-status")).toBe("done"));
    expect(bodyOf(0)).toEqual({ message: "Prep me for my meeting with Brightmoor on Thursday" });
    expect(screen.getByTestId("user-message").textContent).toContain("Brightmoor");
    expect(screen.getAllByTestId(/^section-(?!skeleton)/)).toHaveLength(7);
    const stats = screen.getByTestId("run-stats").textContent!;
    expect(stats).toContain(`$${pack.stats.cost_usd.toFixed(4)}`);
    expect(stats).toContain(String(pack.stats.steps));
    // input is usable again after the run
    expect((screen.getByTestId("chat-input") as HTMLTextAreaElement).disabled).toBe(false);

    const chip = screen.getAllByTestId("citation")[0]!;
    fireEvent.click(chip);
    const panel = await screen.findByTestId("source-panel");
    expect(panel.getAttribute("data-cite")).toBe(chip.getAttribute("data-cite"));
    await waitFor(() => expect(within(panel).queryByTestId("source-loading")).toBeNull());
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("source-panel")).toBeNull();
  });

  it("sends fail_source news when the outage toggle is on, and Enter submits", async () => {
    handler = () => sseResponse(loadRun("brightmoor.news_down").events);
    render(<ChatApp />);
    fireEvent.click(screen.getByTestId("toggle-news-outage"));
    const input = screen.getByTestId("chat-input");
    fireEvent.change(input, { target: { value: "Prep me for Brightmoor" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(screen.getByTestId("assistant-card").getAttribute("data-status")).toBe("done"));
    expect(bodyOf(0)).toEqual({ message: "Prep me for Brightmoor", fail_source: "news" });
    expect(screen.getByTestId("partial-banner")).toBeTruthy();
  });

  it("does not send on Shift+Enter or when empty", () => {
    handler = () => sseResponse([]);
    render(<ChatApp />);
    const input = screen.getByTestId("chat-input");
    fireEvent.change(input, { target: { value: "x" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("disables input while running, offers Stop, and aborts the fetch", async () => {
    const { events } = loadRun("brightmoor.normal");
    const held = streamOf([sseText(events.slice(0, 6))], { hold: true });
    let signal: AbortSignal | undefined;
    handler = (_u, init) => {
      signal = init?.signal ?? undefined;
      signal?.addEventListener("abort", () => held.error(new DOMException("a", "AbortError")));
      return new Response(held.stream);
    };
    render(<ChatApp />);
    fireEvent.click(screen.getByTestId("starter-halden"));
    await waitFor(() => expect(screen.getAllByTestId("timeline-event").length).toBeGreaterThan(3));
    expect((screen.getByTestId("chat-input") as HTMLTextAreaElement).disabled).toBe(true);
    expect((screen.getByTestId("chat-send") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getAllByTestId("agent-lane")).toHaveLength(4);
    await act(async () => fireEvent.click(screen.getByTestId("chat-stop")));
    await waitFor(() => expect(screen.getByTestId("run-stopped")).toBeTruthy());
    expect(signal?.aborted).toBe(true);
    expect((screen.getByTestId("chat-input") as HTMLTextAreaElement).disabled).toBe(false);
  });

  it("shows a friendly error with retry when the API is unreachable", async () => {
    let up = false;
    handler = () => {
      if (!up) throw new TypeError("fetch failed");
      return sseResponse(loadRun("brightmoor.normal").events);
    };
    render(<ChatApp />);
    fireEvent.click(screen.getByTestId("starter-kettle"));
    const err = await screen.findByTestId("run-error");
    expect(err.textContent).toContain("Can't reach the API");
    up = true;
    fireEvent.click(screen.getByTestId("retry-run"));
    await waitFor(() => expect(screen.getByTestId("assistant-card").getAttribute("data-status")).toBe("done"));
    expect(screen.queryByTestId("run-error")).toBeNull();
    expect(screen.getAllByTestId("user-message")).toHaveLength(1);
  });

  it("flags a stream that ends without run_done", async () => {
    const { events } = loadRun("brightmoor.normal");
    handler = () => sseResponse(events.slice(0, 12));
    render(<ChatApp />);
    fireEvent.click(screen.getByTestId("starter-halden"));
    const err = await screen.findByTestId("run-error");
    expect(err.textContent).toContain("The run ended unexpectedly");
  });

  it("skips malformed events with a quiet notice", async () => {
    const { events } = loadRun("brightmoor.normal");
    handler = () =>
      new Response(streamOf([`event: plan\ndata: nope\n\n`, sseText(events)]).stream);
    render(<ChatApp />);
    fireEvent.click(screen.getByTestId("starter-halden"));
    await waitFor(() => expect(screen.getByTestId("assistant-card").getAttribute("data-status")).toBe("done"));
    expect(screen.getByTestId("skipped-notice").textContent).toContain("1 unreadable event was skipped");
  });
});

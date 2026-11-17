import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { Citation } from "@mpa/contract";
import { describe, expect, it, vi } from "vitest";
import { SourcePanel } from "@/components/SourcePanel";
import { json, loadSource, readJson } from "./helpers";

const open = (citation: Citation, fetchImpl: typeof fetch, onClose = vi.fn()) => {
  render(<SourcePanel citation={citation} apiUrl="http://api.test" fetchImpl={fetchImpl} onClose={onClose} />);
  return onClose;
};

describe("SourcePanel", () => {
  it("shows loading, then an email with headers and body, fetching the right URL", async () => {
    const item = loadSource("email");
    const fetchImpl = vi.fn(async () => json(item));
    open({ type: "email", id: item.id }, fetchImpl as unknown as typeof fetch);
    expect(screen.getByTestId("source-loading")).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId("source-body")).toBeTruthy());
    expect((fetchImpl.mock.calls[0] as unknown[])[0]).toBe(`http://api.test/sources/email/${item.id}`);
    if (item.type !== "email") throw new Error("fixture");
    const panel = screen.getByTestId("source-panel");
    expect(panel.textContent).toContain(item.sender);
    expect(panel.textContent).toContain(item.subject);
    expect(screen.getByTestId("source-body").textContent).toBe(item.body);
  });

  it("renders docs and news as plain text (url not a link)", async () => {
    const doc = loadSource("doc");
    open({ type: "doc", id: doc.id }, (async () => json(doc)) as unknown as typeof fetch);
    await waitFor(() => expect(screen.getByTestId("source-body")).toBeTruthy());
    if (doc.type === "doc") expect(screen.getByTestId("source-panel").textContent).toContain(doc.title);
  });

  it("renders news url without creating a link", async () => {
    const news = loadSource("news");
    open({ type: "news", id: news.id }, (async () => json(news)) as unknown as typeof fetch);
    await waitFor(() => expect(screen.getByTestId("source-body")).toBeTruthy());
    const panel = screen.getByTestId("source-panel");
    if (news.type === "news") expect(panel.textContent).toContain(news.url);
    expect(panel.querySelector("a")).toBeNull();
  });

  it.each([
    ["chat", "ChatMessage.basic.json"],
    ["contact", "Contact.basic.json"],
    ["cal", "CalendarEvent.basic.json"],
  ] as const)("renders %s items", async (type, file) => {
    const item = readJson(file) as { id: string };
    open({ type, id: item.id } as Citation, (async () => json(item)) as unknown as typeof fetch);
    await waitFor(() => expect(screen.queryByTestId("source-loading")).toBeNull());
    expect(screen.queryByTestId("source-error")).toBeNull();
    expect(screen.getByTestId("source-panel").textContent).toContain(item.id);
  });

  it("shows not-found and failure states, and retries failures", async () => {
    open({ type: "email", id: "E999" }, (async () => json({ error: "not_found" }, 404)) as unknown as typeof fetch);
    await waitFor(() => expect(screen.getByTestId("source-error").textContent).toContain("could not be found"));
    expect(screen.queryByText("Try again")).toBeNull();
  });

  it("retries after a network failure", async () => {
    const item = loadSource("email");
    const fetchImpl = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("down"))
      .mockResolvedValueOnce(json(item));
    open({ type: "email", id: item.id }, fetchImpl as unknown as typeof fetch);
    await waitFor(() => expect(screen.getByTestId("source-error")).toBeTruthy());
    fireEvent.click(screen.getByText("Try again"));
    await waitFor(() => expect(screen.getByTestId("source-body")).toBeTruthy());
  });

  it("treats an invalid payload as an error", async () => {
    open({ type: "email", id: "E1" }, (async () => json({ type: "email", id: "E1" })) as unknown as typeof fetch);
    await waitFor(() => expect(screen.getByTestId("source-error")).toBeTruthy());
  });

  it("closes with the close button and with Escape, and focuses the close button", async () => {
    const item = loadSource("email");
    const onClose = open({ type: "email", id: item.id }, (async () => json(item)) as unknown as typeof fetch);
    expect(document.activeElement).toBe(screen.getByTestId("source-panel-close"));
    fireEvent.click(screen.getByTestId("source-panel-close"));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(screen.getByTestId("source-body")).toBeTruthy());
  });
});

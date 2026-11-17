import { describe, expect, it, vi } from "vitest";
import { resolveOne, resolveTarget, type LocatorSource } from "../src/targets";

function fakePage() {
  const nth = vi.fn((i: number) => ({ nth: i }));
  const loc = (kind: string) => (...args: unknown[]) => ({ kind, args, nth });
  const page = {
    getByTestId: vi.fn(loc("testId")),
    getByText: vi.fn(loc("text")),
    getByRole: vi.fn(loc("role")),
    locator: vi.fn(loc("css")),
  };
  return { page: page as unknown as LocatorSource, calls: page, nth };
}

describe("target resolution", () => {
  it("maps each target kind to the matching locator factory", () => {
    const { page, calls } = fakePage();
    resolveTarget(page, { testId: "chat-input" });
    resolveTarget(page, { css: ".a" });
    resolveTarget(page, { text: "Hello", exact: true });
    resolveTarget(page, { role: "button", name: "Send" });
    expect(calls.getByTestId).toHaveBeenCalledWith("chat-input");
    expect(calls.locator).toHaveBeenCalledWith(".a");
    expect(calls.getByText).toHaveBeenCalledWith("Hello", { exact: true });
    expect(calls.getByRole).toHaveBeenCalledWith("button", { name: "Send" });
  });

  it("resolveOne defaults to the first match and supports negative nth", () => {
    const a = fakePage();
    resolveOne(a.page, { testId: "x" });
    expect(a.nth).toHaveBeenCalledWith(0);
    const b = fakePage();
    resolveOne(b.page, { testId: "x", nth: -1 });
    expect(b.nth).toHaveBeenCalledWith(-1);
  });
});

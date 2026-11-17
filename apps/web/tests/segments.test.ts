import type { Citation } from "@mpa/contract";
import { describe, expect, it } from "vitest";
import { tokenize, trailingCitations } from "@/lib/segments";
import { readJson } from "./helpers";

describe("tokenize", () => {
  it("splits text and tokens in order", () => {
    expect(tokenize("Budget is 71k [email:E123] and more [doc:D7].")).toEqual([
      { kind: "text", text: "Budget is 71k " },
      { kind: "cite", citation: { type: "email", id: "E123" } },
      { kind: "text", text: " and more " },
      { kind: "cite", citation: { type: "doc", id: "D7" } },
      { kind: "text", text: "." },
    ]);
  });

  it("returns plain text untouched and leaves invalid tokens as text", () => {
    expect(tokenize("no cites")).toEqual([{ kind: "text", text: "no cites" }]);
    expect(tokenize("bad [email:D1] token")).toEqual([{ kind: "text", text: "bad [email:D1] token" }]);
  });

  it("matches the contract's shared citation cases", () => {
    const cases = (readJson("citation_cases.json") as { parse: { name?: string; text: string; expected: Citation[] }[] })
      .parse;
    for (const c of cases) {
      const found = tokenize(c.text).flatMap((s) => (s.kind === "cite" ? [s.citation] : []));
      expect(found, c.name).toEqual(c.expected);
    }
  });
});

describe("trailingCitations", () => {
  it("drops duplicates and citations already inline", () => {
    const cites: Citation[] = [
      { type: "email", id: "E1" },
      { type: "email", id: "E1" },
      { type: "doc", id: "D2" },
    ];
    expect(trailingCitations("see [doc:D2]", cites)).toEqual([{ type: "email", id: "E1" }]);
  });
});

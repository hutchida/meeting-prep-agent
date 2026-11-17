import { describe, expect, it } from "vitest";
import { CONTRACT_VERSION } from "../src/index";

describe("contract skeleton", () => {
  it("exports a version", () => {
    expect(CONTRACT_VERSION).toBeTypeOf("string");
  });
});

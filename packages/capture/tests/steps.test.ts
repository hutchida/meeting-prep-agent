import { describe, expect, it } from "vitest";
import {
  assertValidSteps,
  click,
  describeTarget,
  expectCount,
  expectMarkWithin,
  expectText,
  fill,
  goto,
  mark,
  note,
  press,
  screenshot,
  slugify,
  toggle,
  validateSteps,
  wait,
  waitForNoTestId,
  waitForTestId,
  waitForText,
  type Step,
} from "../src/steps";

describe("step builders", () => {
  it("name steps from kind and target", () => {
    expect(click({ testId: "chat-send" }).name).toBe("click testId=chat-send");
    expect(waitForTestId("briefing").name).toBe("waitForTestId briefing");
    expect(waitForText(/done/i).name).toBe("waitForText /done/i");
    expect(toggle({ testId: "t" }, true).name).toBe("toggle on testId=t");
    expect(toggle({ testId: "t" }).name).toBe("toggle flip testId=t");
    expect(wait(250).name).toBe("wait 250ms");
  });

  it("never puts fill text or url query strings into names", () => {
    expect(fill({ testId: "chat-input" }, "sk-secret-value").name).not.toContain("sk-secret");
    expect(goto("https://example.test/path?token=abc123").name).toBe("goto https://example.test/path");
  });

  it("honours explicit names and timeouts", () => {
    const s = click({ css: ".x" }, { name: "custom", timeoutMs: 500 });
    expect(s).toMatchObject({ name: "custom", timeoutMs: 500 });
  });

  it("describes every target kind", () => {
    expect(describeTarget({ testId: "a", nth: 2 })).toBe("testId=a#2");
    expect(describeTarget({ text: "Hi" })).toBe('text="Hi"');
    expect(describeTarget({ role: "button", name: "Go" })).toBe("role=button[name=Go]");
    expect(describeTarget({ css: ".a > b" })).toBe("css=.a > b");
  });

  it("slugifies labels", () => {
    expect(slugify("Source panel!")).toBe("source-panel");
    expect(slugify("***")).toBe("");
  });
});

describe("step validation", () => {
  const good: Step[] = [
    goto("/"),
    click({ testId: "a" }),
    mark("start"),
    waitForNoTestId("x"),
    expectText({ testId: "a" }, /\S/),
    expectCount({ testId: "a" }, { atLeast: 1 }),
    expectMarkWithin("start", "start", 10),
    screenshot("home"),
    press("Enter"),
    note("hello"),
  ];

  it("accepts a well-formed script", () => {
    expect(validateSteps(good)).toEqual([]);
    expect(() => assertValidSteps(good)).not.toThrow();
  });

  it("rejects empty or non-array input", () => {
    expect(validateSteps([])).toHaveLength(1);
    expect(validateSteps("nope")).toHaveLength(1);
  });

  it("rejects bad targets and values", () => {
    const bad = [
      { kind: "click", name: "a", target: {} },
      { kind: "click", name: "b", target: { testId: "a", css: ".b" } },
      { kind: "goto", name: "c", url: "relative" },
      { kind: "wait", name: "d", ms: -5 },
      { kind: "screenshot", name: "e", label: "!!!", fullPage: false },
      { kind: "mark", name: "f", label: "" },
      { kind: "click", name: "g", target: { testId: "a" }, timeoutMs: 0 },
      { kind: "expectCount", name: "h", target: { testId: "a" }, bounds: {} },
      { kind: "bogus", name: "i" },
      { kind: "click", name: "", target: { testId: "a" } },
    ];
    const problems = validateSteps(bad);
    expect(problems).toHaveLength(bad.length);
    expect(() => assertValidSteps(bad)).toThrow(/Invalid steps/);
  });

  it("requires marks to be unique and referenced after definition", () => {
    expect(validateSteps([mark("a"), mark("a")])).toHaveLength(1);
    expect(validateSteps([expectMarkWithin("b", "a", 10), mark("a"), mark("b")])).toHaveLength(2);
  });
});

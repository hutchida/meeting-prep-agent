import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { failedFileName, findRepoRoot, resolveOutDir, shotFileName } from "../src/paths";
import { errorMessage, redact } from "../src/redact";

describe("file naming", () => {
  it("is deterministic and zero padded", () => {
    expect(shotFileName("demo", 1, "home")).toBe("demo-01-home.png");
    expect(shotFileName("demo", 12, "source-panel")).toBe("demo-12-source-panel.png");
    expect(failedFileName("demo", 7)).toBe("demo-failed-07.png");
  });

  it("resolves relative out dirs against the repo root", () => {
    const root = findRepoRoot();
    expect(path.basename(root)).not.toBe("capture");
    expect(resolveOutDir("docs/media")).toBe(path.join(root, "docs/media"));
    expect(resolveOutDir("/tmp/x")).toBe("/tmp/x");
  });
});

describe("redaction", () => {
  const saved = { ...process.env };
  afterEach(() => {
    process.env = { ...saved };
  });

  it("removes values of sensitive env vars", () => {
    process.env.FAKE_API_KEY = "super-private-value-123";
    process.env.FAKE_BASE_URL = "https://private.example.invalid/v1";
    const msg = redact("failed calling https://private.example.invalid/v1 with super-private-value-123");
    expect(msg).not.toContain("super-private");
    expect(msg).not.toContain("private.example");
  });

  it("removes common secret shapes", () => {
    expect(redact("key sk-abcdefghijklmnop here")).not.toContain("abcdefghij");
    expect(redact("Authorization: Bearer abcdef123456")).not.toContain("abcdef123456");
    expect(redact("api_key=hunter2hunter2")).toBe("api_key=[redacted]");
  });

  it("keeps ordinary text and reduces errors to one clean line", () => {
    expect(redact("click testId=chat-send timed out")).toBe("click testId=chat-send timed out");
    const e = new Error("first \u001b[31mline\u001b[0m\n  call log: secret=abc12345");
    expect(errorMessage(e)).toBe("first line");
  });
});

import { describe, expect, it } from "vitest";
import { assembleGif } from "../src/gif";
import { noisePng, parseGif, solidPng } from "./helpers";

describe("assembleGif", () => {
  it("produces a valid animated GIF with one frame per distinct input", () => {
    const frames = [
      solidPng(400, 250, [255, 255, 255]),
      solidPng(400, 250, [255, 0, 0]),
      solidPng(400, 250, [0, 0, 255]),
    ];
    const gif = assembleGif(frames, { frameDelayMs: 500 });
    const info = parseGif(gif.buffer);
    expect(info.header).toBe("GIF89a");
    expect(info.trailer).toBe(true);
    expect(info.frames).toBe(3);
    expect(gif.frames).toBe(3);
    expect({ w: info.width, h: info.height }).toEqual({ w: 400, h: 250 });
  });

  it("drops consecutive duplicate frames", () => {
    const a = solidPng(100, 80, [1, 2, 3]);
    const gif = assembleGif([a, a, solidPng(100, 80, [9, 9, 9]), a]);
    expect(gif.frames).toBe(3);
  });

  it("downscales wide frames to at most 960 px", () => {
    const gif = assembleGif([solidPng(1280, 800, [20, 40, 60]), solidPng(1280, 800, [60, 40, 20])]);
    const info = parseGif(gif.buffer);
    expect(info.width).toBe(960);
    expect(info.height).toBe(600);
  });

  it("does not upscale small frames", () => {
    expect(assembleGif([solidPng(320, 200, [0, 0, 0])]).width).toBe(320);
  });

  it("reduces quality or frames to respect the size cap", () => {
    const frames = Array.from({ length: 8 }, (_, i) => noisePng(400, 300, i + 1));
    const uncapped = assembleGif(frames, { maxBytes: 100_000_000 });
    const cap = 150_000;
    const capped = assembleGif(frames, { maxBytes: cap });
    expect(uncapped.bytes).toBeGreaterThan(cap);
    expect(capped.withinCap).toBe(true);
    expect(capped.bytes).toBeLessThanOrEqual(cap);
    expect(parseGif(capped.buffer).frames).toBe(capped.frames);
    expect(capped.colors < uncapped.colors || capped.frames < uncapped.frames || capped.width < uncapped.width).toBe(true);
  });

  it("reports when the cap cannot be met", () => {
    const gif = assembleGif([noisePng(300, 300, 7)], { maxBytes: 100 });
    expect(gif.withinCap).toBe(false);
    expect(parseGif(gif.buffer).header).toBe("GIF89a");
  });

  it("rejects an empty frame list", () => {
    expect(() => assembleGif([])).toThrow();
  });
});

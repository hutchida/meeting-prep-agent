import * as gifencNs from "gifenc";
import { PNG } from "pngjs";

type Gifenc = typeof import("gifenc");
const candidates = [gifencNs, (gifencNs as unknown as { default?: unknown }).default] as Partial<Gifenc>[];
const gifenc = candidates.find((c) => typeof c?.GIFEncoder === "function") as Gifenc;
const { applyPalette, GIFEncoder, quantize } = gifenc;

export interface GifOptions {
  frameDelayMs?: number;
  maxWidth?: number;
  maxBytes?: number;
}

export interface GifResult {
  buffer: Buffer;
  width: number;
  height: number;
  frames: number;
  colors: number;
  bytes: number;
  withinCap: boolean;
}

interface Raster {
  width: number;
  height: number;
  data: Uint8Array;
}

export const DEFAULT_GIF_MAX_WIDTH = 960;
export const DEFAULT_GIF_MAX_BYTES = 4 * 1024 * 1024;
const COLOR_LADDER = [256, 128, 64, 32];
const WIDTH_FACTORS = [1, 0.75, 0.5];

function decode(png: Buffer): Raster {
  const img = PNG.sync.read(png);
  return { width: img.width, height: img.height, data: new Uint8Array(img.data) };
}

export function downscale(src: Raster, targetWidth: number): Raster {
  if (src.width <= targetWidth) return src;
  const width = Math.max(1, Math.round(targetWidth));
  const height = Math.max(1, Math.round((src.height * width) / src.width));
  const out = new Uint8Array(width * height * 4);
  const xr = src.width / width;
  const yr = src.height / height;
  for (let y = 0; y < height; y++) {
    const y0 = Math.floor(y * yr);
    const y1 = Math.min(src.height, Math.max(y0 + 1, Math.ceil((y + 1) * yr)));
    for (let x = 0; x < width; x++) {
      const x0 = Math.floor(x * xr);
      const x1 = Math.min(src.width, Math.max(x0 + 1, Math.ceil((x + 1) * xr)));
      let r = 0;
      let g = 0;
      let b = 0;
      let a = 0;
      let n = 0;
      for (let yy = y0; yy < y1; yy++) {
        let i = (yy * src.width + x0) * 4;
        for (let xx = x0; xx < x1; xx++) {
          r += src.data[i] ?? 0;
          g += src.data[i + 1] ?? 0;
          b += src.data[i + 2] ?? 0;
          a += src.data[i + 3] ?? 0;
          n++;
          i += 4;
        }
      }
      const o = (y * width + x) * 4;
      out[o] = Math.round(r / n);
      out[o + 1] = Math.round(g / n);
      out[o + 2] = Math.round(b / n);
      out[o + 3] = Math.round(a / n);
    }
  }
  return { width, height, data: out };
}

function encode(rasters: Raster[], delays: number[], colors: number): Uint8Array {
  const gif = GIFEncoder();
  rasters.forEach((r, i) => {
    const palette = quantize(r.data, colors, { format: "rgb565" });
    const index = applyPalette(r.data, palette, "rgb565");
    gif.writeFrame(index, r.width, r.height, { palette, delay: delays[i] ?? 1000, repeat: 0 });
  });
  gif.finish();
  return gif.bytes();
}

function dropFrames<T>(items: T[]): T[] {
  if (items.length <= 2) return items;
  const last = items.length - 1;
  return items.filter((_, i) => i === 0 || i === last || i % 2 === 0);
}

export function assembleGif(framesPng: Buffer[], opts: GifOptions = {}): GifResult {
  if (framesPng.length === 0) throw new Error("assembleGif needs at least one frame");
  const frameDelayMs = opts.frameDelayMs ?? 1000;
  const maxWidth = opts.maxWidth ?? DEFAULT_GIF_MAX_WIDTH;
  const maxBytes = opts.maxBytes ?? DEFAULT_GIF_MAX_BYTES;

  const unique: Buffer[] = [];
  for (const frame of framesPng) {
    const prev = unique[unique.length - 1];
    if (!prev || !prev.equals(frame)) unique.push(frame);
  }
  const decoded = unique.map(decode);
  const first = decoded[0] as Raster;
  const baseWidth = Math.min(maxWidth, first.width);

  const build = (factor: number, frames: Raster[]): Raster[] =>
    frames.map((f) => downscale(f, Math.max(16, Math.round(baseWidth * factor))));

  let best: { bytes: Uint8Array; rasters: Raster[]; colors: number } | undefined;
  let frames = decoded;
  for (;;) {
    for (const factor of WIDTH_FACTORS) {
      const rasters = build(factor, frames);
      for (const colors of COLOR_LADDER) {
        const bytes = encode(rasters, delaysFor(rasters.length, frameDelayMs), colors);
        best = { bytes, rasters, colors };
        if (bytes.length <= maxBytes) return finish(best, true);
      }
    }
    const next = dropFrames(frames);
    if (next.length === frames.length) break;
    frames = next;
  }
  return finish(best as NonNullable<typeof best>, false);
}

function delaysFor(count: number, frameDelayMs: number): number[] {
  return Array.from({ length: count }, (_, i) => (i === count - 1 ? frameDelayMs * 2 : frameDelayMs));
}

function finish(
  best: { bytes: Uint8Array; rasters: Raster[]; colors: number },
  withinCap: boolean,
): GifResult {
  const first = best.rasters[0] as Raster;
  return {
    buffer: Buffer.from(best.bytes),
    width: first.width,
    height: first.height,
    frames: best.rasters.length,
    colors: best.colors,
    bytes: best.bytes.length,
    withinCap,
  };
}

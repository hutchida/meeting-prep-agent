import { existsSync } from "node:fs";
import { chromium } from "playwright";
import { PNG } from "pngjs";

export function chromiumInstalled(): boolean {
  try {
    return existsSync(chromium.executablePath());
  } catch {
    return false;
  }
}

export const RUN_BROWSER = process.env.RUN_BROWSER_TESTS === "1" || chromiumInstalled();

if (!RUN_BROWSER) {
  console.warn(
    "[capture tests] Chromium not installed: browser tests skipped. " +
      "Run `pnpm --filter @mpa/capture run install-browsers` or set RUN_BROWSER_TESTS=1 to force.",
  );
}

export function solidPng(width: number, height: number, rgb: [number, number, number]): Buffer {
  const png = new PNG({ width, height });
  for (let i = 0; i < width * height; i++) {
    png.data[i * 4] = rgb[0];
    png.data[i * 4 + 1] = rgb[1];
    png.data[i * 4 + 2] = rgb[2];
    png.data[i * 4 + 3] = 255;
  }
  return PNG.sync.write(png);
}

// 8-colour noise: incompressible enough to exercise the cap, cheap to quantize
export function noisePng(width: number, height: number, seed: number): Buffer {
  const png = new PNG({ width, height });
  let x = seed || 1;
  for (let i = 0; i < width * height; i++) {
    for (let c = 0; c < 3; c++) {
      x = (x * 1664525 + 1013904223) >>> 0;
      png.data[i * 4 + c] = x >>> 31 ? 255 : 0;
    }
    png.data[i * 4 + 3] = 255;
  }
  return PNG.sync.write(png);
}

export interface GifInfo {
  header: string;
  width: number;
  height: number;
  frames: number;
  trailer: boolean;
}

export function parseGif(buf: Uint8Array): GifInfo {
  const header = Buffer.from(buf.subarray(0, 6)).toString("ascii");
  const width = (buf[6] ?? 0) | ((buf[7] ?? 0) << 8);
  const height = (buf[8] ?? 0) | ((buf[9] ?? 0) << 8);
  const flags = buf[10] ?? 0;
  let pos = 13;
  if (flags & 0x80) pos += 3 * (1 << ((flags & 7) + 1));
  let frames = 0;
  const skipSubBlocks = () => {
    while ((buf[pos] ?? 0) !== 0) pos += (buf[pos] ?? 0) + 1;
    pos += 1;
  };
  while (pos < buf.length) {
    const b = buf[pos];
    if (b === 0x3b) return { header, width, height, frames, trailer: true };
    if (b === 0x21) {
      pos += 2;
      skipSubBlocks();
    } else if (b === 0x2c) {
      frames++;
      const lf = buf[pos + 9] ?? 0;
      pos += 10;
      if (lf & 0x80) pos += 3 * (1 << ((lf & 7) + 1));
      pos += 1;
      skipSubBlocks();
    } else break;
  }
  return { header, width, height, frames, trailer: false };
}

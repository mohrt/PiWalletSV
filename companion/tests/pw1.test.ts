import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  MultipartAssembler,
  encodeMultipartLines,
  joinMultipartLines,
} from "../src/pw1.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const FIXTURE = join(__dirname, "../../tests/fixtures/proposal_01.cbor");

describe("encodeMultipartLines", () => {
  it("round-trips random bytes", () => {
    const data = new Uint8Array(1024);
    for (let i = 0; i < data.length; i++) data[i] = i & 0xff;
    const lines = encodeMultipartLines(data, 100);
    expect(lines.length).toBeGreaterThan(1);
    const back = joinMultipartLines(lines);
    expect(Array.from(back)).toEqual(Array.from(data));
  });

  it("round-trips proposal_01.cbor fixture", () => {
    // The Phase-2 v2 envelope (Atomic BEEF + raw header chain) is
    // larger than the original fixture, so a 720-byte chunk no longer
    // fits in a single frame. Just assert the multipart codec
    // round-trips cleanly across however many frames it splits into.
    const bytes = new Uint8Array(readFileSync(FIXTURE));
    const lines = encodeMultipartLines(bytes, 720);
    expect(lines.length).toBeGreaterThanOrEqual(1);
    for (const ln of lines) expect(ln.startsWith("PW1|")).toBe(true);
    const back = joinMultipartLines(lines);
    expect(Array.from(back)).toEqual(Array.from(bytes));
  });

  it("matches Python default chunking for fixture", () => {
    // Default is 48 chars/frame (sparse for the Pi camera).
    const bytes = new Uint8Array(readFileSync(FIXTURE));
    const lines = encodeMultipartLines(bytes);
    expect(lines.length).toBeGreaterThanOrEqual(1);
    for (let i = 0; i < lines.length; i++) {
      expect(lines[i].startsWith(`PW1|${lines.length}|${i}|`)).toBe(true);
      // PW1|n|i| + ≤48 payload chars
      expect(lines[i].length).toBeLessThanOrEqual(70);
    }
    const back = joinMultipartLines(lines);
    expect(Array.from(back)).toEqual(Array.from(bytes));
  });

  it("empty payload assembles to empty buffer", () => {
    const asm = new MultipartAssembler();
    expect(asm.feed("PW1|1|0|")).toEqual(new Uint8Array(0));
  });

  it("out-of-order feed completes", () => {
    const data = new Uint8Array(256);
    for (let i = 0; i < data.length; i++) data[i] = (i * 7 + 3) & 0xff;
    const lines = encodeMultipartLines(data, 64);
    expect(lines.length).toBeGreaterThanOrEqual(3);

    const asm = new MultipartAssembler();
    const order = [...lines].reverse();
    let done: Uint8Array | null = null;
    for (const ln of order) {
      const p = asm.feed(ln);
      if (p) done = p;
    }
    expect(done).not.toBeNull();
    expect(Array.from(done!)).toEqual(Array.from(data));
  });

  it("exposes received indices for progress display", () => {
    const data = new Uint8Array(200);
    for (let i = 0; i < data.length; i++) data[i] = i & 0xff;
    const lines = encodeMultipartLines(data, 64);
    const asm = new MultipartAssembler();
    expect(asm.receivedIndices).toEqual([]);
    expect(asm.expectedTotal).toBeNull();
    asm.feed(lines[2]);
    asm.feed(lines[0]);
    expect(asm.receivedIndices).toEqual([0, 2]);
    expect(asm.expectedTotal).toBe(lines.length);
    expect(asm.partsReceived).toBe(2);
  });

  it("ignores non-PW1 lines and is idempotent on duplicates", () => {
    const data = new Uint8Array(200);
    for (let i = 0; i < data.length; i++) data[i] = i & 0xff;
    const lines = encodeMultipartLines(data, 64);
    const asm = new MultipartAssembler();
    expect(asm.feed("not a pw1 line")).toBeNull();
    let done: Uint8Array | null = null;
    for (const ln of [...lines, ...lines]) {
      const p = asm.feed(ln);
      if (p) done = done ?? p;
    }
    expect(done).not.toBeNull();
    expect(Array.from(done!)).toEqual(Array.from(data));
  });
});

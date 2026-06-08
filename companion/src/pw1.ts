/**
 * PW1 multipart QR framing — byte-for-byte compatible with
 * `piwallet.qr.multipart` (Python).
 *
 * Line format: `PW1|<total>|<index>|<base64url_no_padding_fragment>`
 *
 * Browser-safe: uses only Web platform APIs (`atob`, `btoa`, `Uint8Array`).
 * No dependency on `node:buffer`.
 */

export const MAGIC = "PW1";
export const SEP = "|";
export const MIN_ENCODED_CHUNK_CHARS = 64;
// 200 chars ≈ Version 9 QR @ error-correction L (capacity 468 chars).
// A Version 9 matrix is 53×53 modules — at 640×480 capture each module
// is ~8 px wide, well within pyzbar's reliable decode range.
// The previous value of 720 produced Version 17+ QR codes (85×85 modules,
// ~6 px/module) which were too dense for the OV5647 kit camera
// to reliably decode from a screen.
export const DEFAULT_ENCODED_CHUNK_CHARS = 200;

const PREFIX_RE = /^PW1\|(?<t>\d+)\|(?<i>\d+)\|(?<rest>.*)$/;

/** Return ``[total, index]`` for a PW1 line, or ``null`` if not PW1. */
export function pw1LineMeta(line: string): [number, number] | null {
  const m = PREFIX_RE.exec(line.trim());
  if (!m?.groups) return null;
  return [Number(m.groups.t), Number(m.groups.i)];
}

export class MultipartQrError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MultipartQrError";
  }
}

function bytesToBase64Url(bytes: Uint8Array): string {
  // String.fromCharCode(...bytes) blows the JS arg limit for large payloads,
  // so chunk through fromCharCode in 32 KiB blocks.
  let s = "";
  const block = 0x8000;
  for (let i = 0; i < bytes.length; i += block) {
    s += String.fromCharCode(...bytes.subarray(i, i + block));
  }
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlToBytes(b64url: string): Uint8Array {
  const padLen = (4 - (b64url.length % 4)) % 4;
  const b64 = b64url.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat(padLen);
  let bin: string;
  try {
    bin = atob(b64);
  } catch (e) {
    throw new MultipartQrError(`invalid base64 payload: ${(e as Error).message}`);
  }
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export function encodeMultipartLines(
  data: Uint8Array,
  maxEncodedChunkChars: number = DEFAULT_ENCODED_CHUNK_CHARS,
): string[] {
  if (maxEncodedChunkChars < MIN_ENCODED_CHUNK_CHARS) {
    throw new Error(
      `max_encoded_chunk_chars too small (min ${MIN_ENCODED_CHUNK_CHARS})`,
    );
  }

  const blobB64 = bytesToBase64Url(data);
  if (!blobB64) {
    return [`${MAGIC}${SEP}1${SEP}0${SEP}`];
  }

  const nChunks = Math.ceil(blobB64.length / maxEncodedChunkChars);
  const lines: string[] = [];
  for (let i = 0; i < nChunks; i++) {
    const start = i * maxEncodedChunkChars;
    const frag = blobB64.slice(start, start + maxEncodedChunkChars);
    lines.push(`${MAGIC}${SEP}${nChunks}${SEP}${i}${SEP}${frag}`);
  }
  return lines;
}

export class MultipartAssembler {
  private total: number | null = null;
  private readonly parts = new Map<number, string>();

  get expectedTotal(): number | null {
    return this.total;
  }

  get partsReceived(): number {
    return this.parts.size;
  }

  /** Sorted list of fragment indices already received. Useful for UI progress
   *  ("missing: 2, 5, 7"). Empty until at least one PW1 line has been fed. */
  get receivedIndices(): number[] {
    return [...this.parts.keys()].sort((a, b) => a - b);
  }

  reset(): void {
    this.total = null;
    this.parts.clear();
  }

  /**
   * Returns assembled bytes when all fragments have been received, else null.
   * Non-PW1 lines are ignored (return null). Malformed PW1 throws.
   */
  feed(line: string): Uint8Array | null {
    const s = line.trim();
    if (!s.startsWith(`${MAGIC}${SEP}`)) {
      return null;
    }

    const m = PREFIX_RE.exec(s);
    if (!m?.groups) {
      throw new MultipartQrError(
        `bad PW1 line structure: ${s.slice(0, 60)}…`,
      );
    }

    const total = Number(m.groups.t);
    const index = Number(m.groups.i);
    const frag = m.groups.rest;

    if (!Number.isInteger(total) || !Number.isInteger(index)) {
      throw new MultipartQrError(
        `bad total/index: total=${total} index=${index}`,
      );
    }
    if (total < 1 || index < 0 || index >= total) {
      throw new MultipartQrError(
        `bad total/index: total=${total} index=${index}`,
      );
    }

    if (this.total !== null && total !== this.total) {
      this.reset();
    }
    this.total = total;

    if (this.parts.has(index) && this.parts.get(index) !== frag) {
      throw new MultipartQrError(`conflicting fragment at index ${index}`);
    }
    this.parts.set(index, frag);

    if (this.parts.size < total) {
      return null;
    }

    let blobB64 = "";
    for (let i = 0; i < total; i++) {
      const p = this.parts.get(i);
      if (p === undefined) {
        throw new MultipartQrError(`missing fragment index ${i}`);
      }
      blobB64 += p;
    }

    const out = base64UrlToBytes(blobB64);
    this.reset();
    return out;
  }
}

export function joinMultipartLines(lines: Iterable<string>): Uint8Array {
  const asm = new MultipartAssembler();
  let out: Uint8Array | null = null;
  for (const raw of lines) {
    const part = asm.feed(raw.trim());
    if (part !== null) {
      if (out !== null) {
        throw new MultipartQrError("multiple complete payloads in one join call");
      }
      out = part;
    }
  }
  if (out === null) {
    throw new MultipartQrError("incomplete multipart set");
  }
  return out;
}

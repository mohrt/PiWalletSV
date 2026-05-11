/**
 * CBOR + gzip envelope codec — TypeScript counterpart of
 * `piwallet/core/envelope.py`. Same versioned schema, same top-level
 * field names, same kind discriminators.
 *
 * Three envelope kinds round-trip across the QR boundary:
 *   - `xpub`   (Pi → phone, on pairing)
 *   - `tx`     (phone → Pi, unsigned proposal)
 *   - `signed` (Pi → phone, after signing)
 *
 * Wire format: `gzip(cbor(map))`. Map keys are written in the same
 * order Python emits, so CBOR bytes are byte-equivalent on every
 * keystroke a typical implementation makes; gzip output may differ
 * across implementations, but each side always gunzips first so this
 * does not affect interop.
 *
 * Browser-safe: uses Web `CompressionStream` / `DecompressionStream`
 * (Chrome 80+, Safari 16.4+, Firefox 113+, Node 18+). No
 * `node:zlib` / `node:buffer` dependency.
 */
import { Decoder, Encoder } from "cbor-x";

export const ENVELOPE_VERSION = 1;
export const KIND_XPUB = "xpub" as const;
export const KIND_PROPOSAL = "tx" as const;
export const KIND_SIGNED = "signed" as const;

export type EnvelopeKind =
  | typeof KIND_XPUB
  | typeof KIND_PROPOSAL
  | typeof KIND_SIGNED;

const VALID_KINDS: ReadonlySet<string> = new Set<string>([
  KIND_XPUB,
  KIND_PROPOSAL,
  KIND_SIGNED,
]);

export class EnvelopeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EnvelopeError";
  }
}

// ---------------------------------------------------------------------------
// Type definitions for the three decoded envelope shapes.
// ---------------------------------------------------------------------------

export interface XpubExportT {
  kind: typeof KIND_XPUB;
  xpub: string;
  path: string;
  label: string;
  /** 4-byte self-fingerprint (`hash160(pubkey)[:4]`). */
  fingerprint: Uint8Array;
}

export interface ProposalInputT {
  txid: string;
  vout: number;
  sats: number;
  /** BEEF bytes for the prior tx funding this input. */
  beef: Uint8Array;
  /** Structured MerklePath (`MerklePath.to_binary()` on the Pi side). */
  merklePath: Uint8Array;
  /** `[change_branch, index]` the Pi will use to re-derive the signing key. */
  derivation: [number, number];
}

export interface ProposalOutputT {
  /** Locking script as hex (P2PKH for v1). */
  scriptHex: string;
  sats: number;
}

export interface UnsignedProposalT {
  kind: typeof KIND_PROPOSAL;
  /** 4-byte fingerprint of the wallet xpub the Pi must sign with. */
  walletFp: Uint8Array;
  inputs: ProposalInputT[];
  outputs: ProposalOutputT[];
  changeIndex: number;
  changeDerivation: [number, number];
  feeRate: number;
  locktime: number;
  /** height → 32-byte merkle root; the Pi cross-checks every input's path. */
  headerAnchors: Map<number, Uint8Array>;
}

export interface SignedTxT {
  kind: typeof KIND_SIGNED;
  walletFp: Uint8Array;
  rawHex: string;
  txid: string;
}

export type Envelope = XpubExportT | UnsignedProposalT | SignedTxT;

// ---------------------------------------------------------------------------
// CBOR + gzip helpers.
// ---------------------------------------------------------------------------

const cborEncoder = new Encoder({
  useRecords: false,
  structuredClone: false,
  mapsAsObjects: false,
  tagUint8Array: false,
  largeBigIntToFloat: false,
});

const cborDecoder = new Decoder({
  useRecords: false,
  structuredClone: false,
  mapsAsObjects: false,
  tagUint8Array: false,
  largeBigIntToFloat: false,
});

function asU8(v: Uint8Array | ArrayBuffer): Uint8Array {
  if (v instanceof Uint8Array) {
    return new Uint8Array(v.buffer, v.byteOffset, v.byteLength);
  }
  return new Uint8Array(v);
}

async function gzipBytes(data: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([data])
    .stream()
    .pipeThrough(new CompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

async function gunzipBytes(data: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([data])
    .stream()
    .pipeThrough(new DecompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

// ---------------------------------------------------------------------------
// Encoding.
// ---------------------------------------------------------------------------

function envelopeToCborBody(env: Envelope): Map<string, unknown> {
  const m = new Map<string, unknown>();
  m.set("v", ENVELOPE_VERSION);
  m.set("kind", env.kind);
  if (env.kind === KIND_XPUB) {
    m.set("xpub", env.xpub);
    m.set("path", env.path);
    m.set("label", env.label);
    m.set("fp", env.fingerprint);
    return m;
  }
  if (env.kind === KIND_PROPOSAL) {
    m.set("walletFp", env.walletFp);
    m.set(
      "inputs",
      env.inputs.map((i) => {
        const im = new Map<string, unknown>();
        im.set("txid", i.txid);
        im.set("vout", i.vout);
        im.set("sats", i.sats);
        im.set("beef", i.beef);
        im.set("merklePath", i.merklePath);
        im.set("derivation", [...i.derivation]);
        return im;
      }),
    );
    m.set(
      "outputs",
      env.outputs.map((o) => {
        const om = new Map<string, unknown>();
        om.set("script", o.scriptHex);
        om.set("sats", o.sats);
        return om;
      }),
    );
    m.set("changeIndex", env.changeIndex);
    m.set("changeDerivation", [...env.changeDerivation]);
    m.set("feeRate", env.feeRate);
    m.set("locktime", env.locktime);
    m.set("headerAnchors", env.headerAnchors);
    return m;
  }
  // KIND_SIGNED
  m.set("walletFp", env.walletFp);
  m.set("rawHex", env.rawHex);
  m.set("txid", env.txid);
  return m;
}

export async function encodeEnvelope(env: Envelope): Promise<Uint8Array> {
  const body = envelopeToCborBody(env);
  const cborBytes = asU8(cborEncoder.encode(body));
  return gzipBytes(cborBytes);
}

// ---------------------------------------------------------------------------
// Decoding.
// ---------------------------------------------------------------------------

type CborMap = Map<unknown, unknown>;

function isCborMap(v: unknown): v is CborMap {
  return v instanceof Map;
}

function requireString(m: CborMap, key: string, ctx: string): string {
  const v = m.get(key);
  if (typeof v !== "string") {
    throw new EnvelopeError(`${ctx}: '${key}' must be a string`);
  }
  return v;
}

function requireBytes(
  m: CborMap,
  key: string,
  ctx: string,
  expectedLen?: number,
): Uint8Array {
  const v = m.get(key);
  if (!(v instanceof Uint8Array)) {
    throw new EnvelopeError(`${ctx}: '${key}' must be bytes`);
  }
  if (expectedLen !== undefined && v.length !== expectedLen) {
    throw new EnvelopeError(
      `${ctx}: '${key}' must be ${expectedLen} bytes, got ${v.length}`,
    );
  }
  return new Uint8Array(v);
}

function asNumber(v: unknown, ctx: string, key: string): number {
  if (typeof v === "number") return v;
  if (typeof v === "bigint") {
    if (
      v > BigInt(Number.MAX_SAFE_INTEGER) ||
      v < BigInt(Number.MIN_SAFE_INTEGER)
    ) {
      throw new EnvelopeError(
        `${ctx}: '${key}' (${v}) out of safe integer range`,
      );
    }
    return Number(v);
  }
  throw new EnvelopeError(`${ctx}: '${key}' must be a number, got ${typeof v}`);
}

function requireNumber(m: CborMap, key: string, ctx: string): number {
  return asNumber(m.get(key), ctx, key);
}

function requireKeys(m: CborMap, keys: readonly string[], ctx: string): void {
  const missing = keys.filter((k) => !m.has(k));
  if (missing.length > 0) {
    throw new EnvelopeError(
      `${ctx}: missing required key(s) ${missing.sort().join(", ")}`,
    );
  }
}

function parseDerivation(v: unknown, ctx: string): [number, number] {
  if (!Array.isArray(v) || v.length !== 2) {
    throw new EnvelopeError(`${ctx}: derivation must be [branch, index]`);
  }
  return [asNumber(v[0], ctx, "derivation[0]"), asNumber(v[1], ctx, "derivation[1]")];
}

function parseInput(raw: unknown, idx: number): ProposalInputT {
  if (!isCborMap(raw)) {
    throw new EnvelopeError(`input[${idx}] must be a map`);
  }
  const ctx = `input[${idx}]`;
  requireKeys(
    raw,
    ["txid", "vout", "sats", "beef", "merklePath", "derivation"],
    ctx,
  );
  return {
    txid: requireString(raw, "txid", ctx),
    vout: requireNumber(raw, "vout", ctx),
    sats: requireNumber(raw, "sats", ctx),
    beef: requireBytes(raw, "beef", ctx),
    merklePath: requireBytes(raw, "merklePath", ctx),
    derivation: parseDerivation(raw.get("derivation"), ctx),
  };
}

function parseOutput(raw: unknown, idx: number): ProposalOutputT {
  if (!isCborMap(raw)) {
    throw new EnvelopeError(`output[${idx}] must be a map`);
  }
  const ctx = `output[${idx}]`;
  requireKeys(raw, ["script", "sats"], ctx);
  return {
    scriptHex: requireString(raw, "script", ctx),
    sats: requireNumber(raw, "sats", ctx),
  };
}

function parseXpub(body: CborMap): XpubExportT {
  requireKeys(body, ["xpub", "path", "label", "fp"], "xpub_export");
  return {
    kind: KIND_XPUB,
    xpub: requireString(body, "xpub", "xpub_export"),
    path: requireString(body, "path", "xpub_export"),
    label: requireString(body, "label", "xpub_export"),
    fingerprint: requireBytes(body, "fp", "xpub_export", 4),
  };
}

function parseProposal(body: CborMap): UnsignedProposalT {
  requireKeys(
    body,
    [
      "walletFp",
      "inputs",
      "outputs",
      "changeIndex",
      "changeDerivation",
      "feeRate",
    ],
    "unsigned_proposal",
  );
  const walletFp = requireBytes(body, "walletFp", "unsigned_proposal", 4);

  const rawInputs = body.get("inputs");
  if (!Array.isArray(rawInputs) || rawInputs.length === 0) {
    throw new EnvelopeError("unsigned_proposal: 'inputs' must be a non-empty array");
  }
  const inputs = rawInputs.map((i, idx) => parseInput(i, idx));

  const rawOutputs = body.get("outputs");
  if (!Array.isArray(rawOutputs) || rawOutputs.length === 0) {
    throw new EnvelopeError("unsigned_proposal: 'outputs' must be a non-empty array");
  }
  const outputs = rawOutputs.map((o, idx) => parseOutput(o, idx));

  const changeIndex = requireNumber(body, "changeIndex", "unsigned_proposal");
  if (
    !Number.isInteger(changeIndex) ||
    changeIndex < 0 ||
    changeIndex >= outputs.length
  ) {
    throw new EnvelopeError(
      `unsigned_proposal: changeIndex ${changeIndex} out of range for ${outputs.length} outputs`,
    );
  }

  const changeDerivation = parseDerivation(
    body.get("changeDerivation"),
    "unsigned_proposal.changeDerivation",
  );

  const feeRate = requireNumber(body, "feeRate", "unsigned_proposal");
  const locktime = body.has("locktime")
    ? requireNumber(body, "locktime", "unsigned_proposal")
    : 0;

  const headerAnchors = new Map<number, Uint8Array>();
  const anchorsRaw = body.get("headerAnchors");
  if (anchorsRaw !== undefined && anchorsRaw !== null) {
    if (!isCborMap(anchorsRaw)) {
      throw new EnvelopeError(
        "unsigned_proposal: 'headerAnchors' must be a map of height → 32 bytes",
      );
    }
    for (const [h, r] of anchorsRaw) {
      const height =
        typeof h === "number"
          ? h
          : typeof h === "bigint"
            ? Number(h)
            : Number.NaN;
      if (!Number.isInteger(height)) {
        throw new EnvelopeError(
          `headerAnchors: keys must be integers, got ${typeof h}`,
        );
      }
      if (!(r instanceof Uint8Array) || r.length !== 32) {
        throw new EnvelopeError(`headerAnchors[${height}] must be 32 bytes`);
      }
      headerAnchors.set(height, new Uint8Array(r));
    }
  }

  return {
    kind: KIND_PROPOSAL,
    walletFp,
    inputs,
    outputs,
    changeIndex,
    changeDerivation,
    feeRate,
    locktime,
    headerAnchors,
  };
}

function parseSignedTx(body: CborMap): SignedTxT {
  requireKeys(body, ["walletFp", "rawHex", "txid"], "signed_tx");
  return {
    kind: KIND_SIGNED,
    walletFp: requireBytes(body, "walletFp", "signed_tx", 4),
    rawHex: requireString(body, "rawHex", "signed_tx"),
    txid: requireString(body, "txid", "signed_tx"),
  };
}

export async function decodeEnvelope(blob: Uint8Array): Promise<Envelope> {
  let cborBytes: Uint8Array;
  try {
    cborBytes = await gunzipBytes(blob);
  } catch (e) {
    throw new EnvelopeError(`gzip decompress failed: ${(e as Error).message}`);
  }
  let body: unknown;
  try {
    body = cborDecoder.decode(cborBytes);
  } catch (e) {
    throw new EnvelopeError(`CBOR decode failed: ${(e as Error).message}`);
  }
  if (!isCborMap(body)) {
    throw new EnvelopeError(
      `top-level CBOR must be a map, got ${typeof body}`,
    );
  }

  const version = body.get("v");
  if (version !== ENVELOPE_VERSION) {
    throw new EnvelopeError(`unsupported envelope version: ${String(version)}`);
  }
  const kind = body.get("kind");
  if (typeof kind !== "string" || !VALID_KINDS.has(kind)) {
    throw new EnvelopeError(`unknown envelope kind: ${String(kind)}`);
  }

  if (kind === KIND_XPUB) return parseXpub(body);
  if (kind === KIND_PROPOSAL) return parseProposal(body);
  return parseSignedTx(body);
}

// ---------------------------------------------------------------------------
// Hex helpers — convenient for surfaces that don't want to deal with bytes.
// ---------------------------------------------------------------------------

export function bytesToHex(bytes: Uint8Array): string {
  let hex = "";
  for (const b of bytes) hex += b.toString(16).padStart(2, "0");
  return hex;
}

export function hexToBytes(hex: string): Uint8Array {
  const clean = hex.replace(/\s+/g, "").toLowerCase();
  if (clean.length % 2 !== 0 || /[^0-9a-f]/.test(clean)) {
    throw new EnvelopeError("invalid hex string");
  }
  const out = new Uint8Array(clean.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(clean.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}

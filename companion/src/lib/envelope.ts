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

/**
 * Current envelope schema version, kept byte-identical with the Pi-side
 * `piwallet.core.envelope.ENVELOPE_VERSION`.
 *
 * History:
 *   v1 — initial release.
 *   v2 — drop the redundant per-input `merklePath` field (BEEF carries
 *        it once), switch `signed_tx` to a single `atomicBeef`
 *        Uint8Array (BRC-95). v1 envelopes are intentionally rejected
 *        so an out-of-sync producer surfaces clearly.
 */
export const ENVELOPE_VERSION = 2;
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

/**
 * Network discriminator stamped on every xpub_export envelope from a
 * v1.1+ Pi build. The companion uses this to pick the matching
 * base58check P2PKH prefix and the WhatsOnChain endpoint when the
 * paired wallet is queried. See `protocol/envelopes.md` §3.
 */
export type NetworkT = "main" | "test";

const VALID_NETWORKS: ReadonlySet<string> = new Set(["main", "test"]);

export interface XpubExportT {
  kind: typeof KIND_XPUB;
  xpub: string;
  path: string;
  label: string;
  /** 4-byte self-fingerprint (`hash160(pubkey)[:4]`). */
  fingerprint: Uint8Array;
  /**
   * Wallet's network. Pre-v1.1 envelopes lack this field; the
   * decoder forward-migrates absent values to `"main"` to preserve
   * existing pairings.
   */
  network: NetworkT;
}

export interface ProposalInputT {
  txid: string;
  vout: number;
  sats: number;
  /**
   * BRC-62 BEEF bytes for the prior transaction funding this input.
   * The BEEF carries the prior tx itself plus its BRC-74 BUMP Merkle
   * path; the standalone per-input ``merklePath`` field that earlier
   * envelope revisions also carried was removed in v2 because it was
   * always redundant with this payload.
   */
  beef: Uint8Array;
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
  /**
   * Height of the firmware checkpoint the ``headers`` chain links
   * back to. The first entry in ``headers`` MUST live at
   * ``checkpointHeight + 1``; the Pi rejects the proposal otherwise.
   * The companion picks this height from
   * {@link "./headers.js".checkpointFor}.
   */
  checkpointHeight: number;
  /**
   * Contiguous list of 80-byte headers in ascending height order,
   * starting at ``checkpointHeight + 1``. The Pi PoW-validates this
   * chain on receipt and uses the resulting per-height merkle roots
   * to verify each input's BEEF Merkle path.
   */
  headers: Uint8Array[];
}

export interface SignedTxT {
  kind: typeof KIND_SIGNED;
  walletFp: Uint8Array;
  /**
   * Signed transaction in **Atomic BEEF (BRC-95)** form: a 4-byte
   * magic ``0x01010101``, the 32-byte subject TXID in raw byte order,
   * and a regular BRC-62 BEEF body. Consumers can recover the raw
   * signed-tx hex via ``Transaction.fromAtomicBEEF`` (or the helpers
   * exported from this module). The previously-separate ``rawHex`` /
   * ``txid`` fields were dropped in envelope v2: ``rawHex`` is
   * reproducible from the BEEF body, and ``txid`` is already declared
   * in the BRC-95 header.
   */
  atomicBeef: Uint8Array;
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
    m.set("net", env.network);
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
    m.set("checkpointHeight", env.checkpointHeight);
    m.set("headers", env.headers);
    return m;
  }
  // KIND_SIGNED
  m.set("walletFp", env.walletFp);
  m.set("atomicBeef", env.atomicBeef);
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
  requireKeys(raw, ["txid", "vout", "sats", "beef", "derivation"], ctx);
  return {
    txid: requireString(raw, "txid", ctx),
    vout: requireNumber(raw, "vout", ctx),
    sats: requireNumber(raw, "sats", ctx),
    beef: requireBytes(raw, "beef", ctx),
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
  // `net` is OPTIONAL on the wire: pre-v1.1 envelopes lack the
  // field, and we treat its absence as "main" so existing pairings
  // keep working when the operator upgrades the Pi but not the PWA
  // (or vice versa).
  let network: NetworkT = "main";
  if (body.has("net")) {
    const raw = body.get("net");
    if (typeof raw !== "string" || !VALID_NETWORKS.has(raw)) {
      throw new EnvelopeError(
        `xpub_export: 'net' must be "main" or "test", got ${JSON.stringify(raw)}`,
      );
    }
    network = raw as NetworkT;
  }
  return {
    kind: KIND_XPUB,
    xpub: requireString(body, "xpub", "xpub_export"),
    path: requireString(body, "path", "xpub_export"),
    label: requireString(body, "label", "xpub_export"),
    fingerprint: requireBytes(body, "fp", "xpub_export", 4),
    network,
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
      "checkpointHeight",
      "headers",
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

  const checkpointHeight = requireNumber(
    body,
    "checkpointHeight",
    "unsigned_proposal",
  );
  if (!Number.isInteger(checkpointHeight) || checkpointHeight < 0) {
    throw new EnvelopeError(
      `unsigned_proposal: checkpointHeight ${checkpointHeight} must be a non-negative integer`,
    );
  }

  const headersRaw = body.get("headers");
  if (!Array.isArray(headersRaw)) {
    throw new EnvelopeError(
      "unsigned_proposal: 'headers' must be a list of 80-byte byte strings",
    );
  }
  const headers: Uint8Array[] = headersRaw.map((h, idx) => {
    if (!(h instanceof Uint8Array) || h.length !== 80) {
      const len = h instanceof Uint8Array ? h.length : "n/a";
      throw new EnvelopeError(
        `unsigned_proposal: headers[${idx}] must be 80 bytes, got ${len}`,
      );
    }
    return new Uint8Array(h);
  });

  return {
    kind: KIND_PROPOSAL,
    walletFp,
    inputs,
    outputs,
    changeIndex,
    changeDerivation,
    feeRate,
    locktime,
    checkpointHeight,
    headers,
  };
}

function parseSignedTx(body: CborMap): SignedTxT {
  requireKeys(body, ["walletFp", "atomicBeef"], "signed_tx");
  return {
    kind: KIND_SIGNED,
    walletFp: requireBytes(body, "walletFp", "signed_tx", 4),
    atomicBeef: requireBytes(body, "atomicBeef", "signed_tx"),
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
// Atomic BEEF (BRC-95) helpers.
//
// Used by the scanner to surface the txid declared in a signed_tx
// envelope and to recover the raw signed-tx hex for broadcast. Pure
// byte-level helpers; no `@bsv/sdk` dependency so we can run them in
// environments where the SDK isn't loaded.
// ---------------------------------------------------------------------------

const ATOMIC_BEEF_MAGIC = new Uint8Array([0x01, 0x01, 0x01, 0x01]);
const ATOMIC_BEEF_HEADER_LEN = 4 + 32;

export class AtomicBeefError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AtomicBeefError";
  }
}

/**
 * Split a BRC-95 Atomic BEEF blob into its `(subjectTxidHex, body)`
 * components. ``subjectTxidHex`` is rendered in the displayed form
 * (big-endian hex), which is the inverse of how it appears on the
 * wire. ``body`` is a fresh ``Uint8Array`` view on the inner regular
 * BEEF (BRC-62) bytes.
 */
export function splitAtomicBeef(blob: Uint8Array): {
  subjectTxidHex: string;
  body: Uint8Array;
} {
  if (!(blob instanceof Uint8Array)) {
    throw new AtomicBeefError("atomic beef blob must be Uint8Array");
  }
  if (blob.length < ATOMIC_BEEF_HEADER_LEN) {
    throw new AtomicBeefError(
      `atomic beef blob is ${blob.length} bytes; need at least ${ATOMIC_BEEF_HEADER_LEN}`,
    );
  }
  for (let i = 0; i < 4; i++) {
    if (blob[i] !== ATOMIC_BEEF_MAGIC[i]) {
      const got = bytesToHex(blob.slice(0, 4));
      throw new AtomicBeefError(
        `atomic beef magic mismatch: expected 01010101, got ${got}`,
      );
    }
  }
  // Subject txid is stored in raw byte order on the wire; the displayed
  // form is the byte-reversal.
  const txidWire = blob.slice(4, 36);
  const subjectTxidHex = bytesToHex(txidWire.slice().reverse());
  const body = blob.slice(ATOMIC_BEEF_HEADER_LEN);
  return { subjectTxidHex, body };
}

/**
 * Convenience: peel the subject TXID off an Atomic BEEF blob without
 * parsing the inner BEEF body. Used when a caller only needs to label
 * a UI surface, not actually broadcast.
 */
export function atomicBeefTxid(blob: Uint8Array): string {
  return splitAtomicBeef(blob).subjectTxidHex;
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

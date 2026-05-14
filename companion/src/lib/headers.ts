/**
 * Block-header parsing, PoW validation, and an IndexedDB-backed cache
 * of validated headers — TypeScript counterpart of
 * `piwallet/core/headers.py`.
 *
 * The companion uses this module two ways:
 *
 * 1. **Send-side sanity check.** Before shipping an unsigned-proposal
 *    envelope to the Pi, the companion calls {@link verifyChain} on
 *    the raw 80-byte header list to catch a misbehaving WoC mirror
 *    early — the Pi rejection message would otherwise have to travel
 *    back across the QR boundary.
 * 2. **Receive-side SPV.** Every UTXO returned by
 *    {@link "./woc.js".WocClient.getUnspentBatch} is anchored to a
 *    block height and a Merkle proof. The companion fetches the
 *    relevant header (cached locally), validates PoW + linkage all
 *    the way from the firmware checkpoint, then verifies the proof
 *    against the validated merkle root before counting the UTXO
 *    toward balance. This mirrors what the Pi does on the input
 *    side; both ends of the air-gap therefore enforce BRC-67 SPV.
 *
 * The pure-byte primitives ({@link parseHeader}, {@link headerHash},
 * {@link bitsToTarget}, {@link verifyPow}, {@link verifyChain}) are
 * deliberately framework-free so they round-trip cleanly under
 * `vitest`. The IndexedDB cache lives below them and is opt-in.
 */

import { sha256 } from "@noble/hashes/sha2.js";

import type { NetworkT } from "./envelope.js";
import { bytesToHex, hexToBytes } from "./envelope.js";

export const HEADER_SIZE = 80;

export class HeaderError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "HeaderError";
  }
}

export interface BlockHeader {
  /** Little-endian uint32 from the wire. */
  version: number;
  /** Predecessor's double-SHA256, raw byte order (32 bytes). */
  prevHash: Uint8Array;
  /** Block's Merkle root, raw byte order (32 bytes). */
  merkleRoot: Uint8Array;
  /** Miner-reported UNIX timestamp (uint32). */
  time: number;
  /** Compact target (uint32). */
  bits: number;
  /** PoW nonce (uint32). */
  nonce: number;
  /** The 80-byte serialization, kept verbatim for re-hashing. */
  raw: Uint8Array;
}

// ---------------------------------------------------------------------------
// Pure primitives.
// ---------------------------------------------------------------------------

function readU32LE(bytes: Uint8Array, offset: number): number {
  return (
    (bytes[offset] |
      (bytes[offset + 1] << 8) |
      (bytes[offset + 2] << 16) |
      (bytes[offset + 3] << 24)) >>>
    0
  );
}

function writeU32LE(value: number, out: Uint8Array, offset: number): void {
  out[offset] = value & 0xff;
  out[offset + 1] = (value >>> 8) & 0xff;
  out[offset + 2] = (value >>> 16) & 0xff;
  out[offset + 3] = (value >>> 24) & 0xff;
}

/**
 * Decode an 80-byte header into its constituent fields.
 *
 * Per-field validation (PoW, linkage) is the job of
 * {@link verifyChain}; this function is purely structural.
 */
export function parseHeader(blob: Uint8Array): BlockHeader {
  if (!(blob instanceof Uint8Array)) {
    throw new HeaderError("header must be a Uint8Array");
  }
  if (blob.length !== HEADER_SIZE) {
    throw new HeaderError(
      `header must be ${HEADER_SIZE} bytes, got ${blob.length}`,
    );
  }
  const raw = new Uint8Array(blob);
  return {
    version: readU32LE(raw, 0),
    prevHash: raw.slice(4, 36),
    merkleRoot: raw.slice(36, 68),
    time: readU32LE(raw, 68),
    bits: readU32LE(raw, 72),
    nonce: readU32LE(raw, 76),
    raw,
  };
}

/**
 * Double-SHA256 of an 80-byte header in *raw* byte order.
 *
 * The displayed (big-endian) hex form is the byte-reverse of this
 * value. Use {@link bytesToHex} on `headerHash(raw).slice().reverse()`
 * to render the displayed form.
 */
export function headerHash(blob: Uint8Array): Uint8Array {
  if (!(blob instanceof Uint8Array)) {
    throw new HeaderError("header must be a Uint8Array");
  }
  if (blob.length !== HEADER_SIZE) {
    throw new HeaderError(
      `header must be ${HEADER_SIZE} bytes, got ${blob.length}`,
    );
  }
  return sha256(sha256(blob));
}

/**
 * Decode a Bitcoin-style compact ``bits`` field into a 256-bit
 * difficulty target. Mirrors the Python implementation and refuses to
 * decode a target with the sign bit set.
 */
export function bitsToTarget(bits: number): bigint {
  if (!Number.isInteger(bits) || bits < 0 || bits > 0xffffffff) {
    throw new HeaderError(`bits must be a uint32, got ${bits}`);
  }
  if ((bits & 0x00800000) !== 0) {
    throw new HeaderError(
      `bits 0x${bits.toString(16).padStart(8, "0")} has the sign bit set`,
    );
  }
  const exponent = (bits >>> 24) & 0xff;
  const mantissa = BigInt(bits & 0x007fffff);
  if (mantissa === 0n) return 0n;
  let target: bigint;
  if (exponent <= 3) {
    target = mantissa >> BigInt(8 * (3 - exponent));
  } else {
    target = mantissa << BigInt(8 * (exponent - 3));
  }
  if (target >> 256n !== 0n) {
    throw new HeaderError(
      `bits 0x${bits.toString(16).padStart(8, "0")} decodes to >256-bit target`,
    );
  }
  return target;
}

/** Interpret a 32-byte hash in raw byte order as a uint256. */
function hashAsUint256LE(hash: Uint8Array): bigint {
  let acc = 0n;
  for (let i = hash.length - 1; i >= 0; i--) {
    acc = (acc << 8n) | BigInt(hash[i]);
  }
  return acc;
}

/**
 * Throw if a parsed header's hash exceeds the target encoded by its
 * own ``bits`` field.
 */
export function verifyPow(header: BlockHeader): void {
  const target = bitsToTarget(header.bits);
  const h = hashAsUint256LE(headerHash(header.raw));
  if (h > target) {
    const displayed = bytesToHex(headerHash(header.raw).slice().reverse());
    throw new HeaderError(`header ${displayed} fails PoW: hash > target`);
  }
}

/**
 * Trusted starting point for a chain walk. The companion's job is to
 * ship the contiguous list of headers that descends from this anchor
 * to the deepest block height the proposal touches.
 */
export interface CheckpointHeader {
  height: number;
  /** Double-SHA256 of the checkpoint's 80-byte header, raw byte order. */
  hash: Uint8Array;
}

// ---------------------------------------------------------------------------
// Hard-coded checkpoints (mirror of `piwallet/core/checkpoints.py`).
//
// The Pi ships these baked into firmware; the companion ships an
// identical copy so the local sanity check uses the same trust
// anchor the Pi will. When a firmware release rotates `*_RECENT`,
// the companion's copy MUST be rotated in the same release — see
// `docs/protocol/headers.md` for the update procedure.
// ---------------------------------------------------------------------------

/** Bitcoin / BSV mainnet genesis block (height 0). */
export const MAINNET_GENESIS_HEADER_HEX =
  "01000000" +
  "0000000000000000000000000000000000000000000000000000000000000000" +
  "3ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa4b1e5e4a" +
  "29ab5f49" +
  "ffff001d" +
  "1dac2b7c";
/** BSV testnet3 genesis block (height 0). */
export const TESTNET_GENESIS_HEADER_HEX =
  "01000000" +
  "0000000000000000000000000000000000000000000000000000000000000000" +
  "3ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa4b1e5e4a" +
  "dae5494d" +
  "ffff001d" +
  "1aa4ae18";

function checkpointFromGenesis(rawHex: string): CheckpointHeader {
  const raw = hexToBytes(rawHex);
  return { height: 0, hash: headerHash(raw) };
}

/**
 * Resolve the active firmware checkpoint for ``network``.
 *
 * The companion ships the genesis-block fallback for both networks;
 * production firmware builds rotate to a recent height (~4 weeks
 * deep) so the per-proposal header-chain payload stays bounded. Both
 * sides MUST agree on the checkpoint, so this resolver is the
 * single source of truth on the companion side.
 */
export function checkpointFor(network: NetworkT): CheckpointHeader {
  if (network === "main") {
    return checkpointFromGenesis(MAINNET_GENESIS_HEADER_HEX);
  }
  if (network === "test") {
    return checkpointFromGenesis(TESTNET_GENESIS_HEADER_HEX);
  }
  throw new HeaderError(
    `unknown network ${JSON.stringify(network)}; expected "main" or "test"`,
  );
}

export function bytesEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

/**
 * Walk a sequence of consecutive 80-byte headers starting from
 * ``checkpoint``. Returns ``height -> merkle root`` for every header
 * in the input (heights start at ``checkpoint.height + 1`` and are
 * dense). Throws on the first failure.
 *
 * Mirrors `piwallet.core.headers.verify_chain` byte-for-byte so the
 * companion's send-side sanity check matches what the Pi will reject.
 */
export function verifyChain(
  headers: Iterable<Uint8Array>,
  checkpoint: CheckpointHeader,
): Map<number, Uint8Array> {
  const out = new Map<number, Uint8Array>();
  let expectedPrev = checkpoint.hash;
  let count = 0;
  let height = checkpoint.height;
  for (const blob of headers) {
    height = checkpoint.height + count + 1;
    let parsed: BlockHeader;
    try {
      parsed = parseHeader(blob);
    } catch (e) {
      throw new HeaderError(`height ${height}: ${(e as Error).message}`);
    }
    if (!bytesEqual(parsed.prevHash, expectedPrev)) {
      const exp = bytesToHex(expectedPrev.slice().reverse());
      const got = bytesToHex(parsed.prevHash.slice().reverse());
      throw new HeaderError(
        `height ${height}: prev_hash mismatch (expected ${exp}, got ${got})`,
      );
    }
    try {
      verifyPow(parsed);
    } catch (e) {
      throw new HeaderError(`height ${height}: ${(e as Error).message}`);
    }
    out.set(height, parsed.merkleRoot);
    expectedPrev = headerHash(parsed.raw);
    count += 1;
  }
  if (count === 0) {
    throw new HeaderError("verifyChain called with an empty header sequence");
  }
  return out;
}

// ---------------------------------------------------------------------------
// JSON header reconstruction.
//
// WoC's `GET /block/{hashOrHeight}/header` returns a JSON document with
// the seven 80-byte fields in human-readable form. We reconstruct the
// canonical wire bytes locally so both the companion's PoW pipeline and
// the bytes shipped to the Pi descend from the same source of truth.
// ---------------------------------------------------------------------------

export interface WocHeaderJson {
  hash: string;
  height: number;
  version: number;
  /** Hex string of the compact target, e.g. ``"180997ee"``. */
  bits: string;
  nonce: number;
  merkleroot: string;
  time: number;
  /** Absent on the genesis block. */
  previousblockhash?: string;
}

const ZERO32 = new Uint8Array(32);

/**
 * Reconstruct an 80-byte raw header from a WoC JSON header response.
 *
 * Throws if any field is malformed. The output is verified by
 * recomputing its hash and matching it against the JSON's declared
 * `hash`; this catches a WoC response that's internally inconsistent
 * before the bytes flow into PoW validation.
 */
export function rawHeaderFromJson(j: WocHeaderJson): Uint8Array {
  if (!Number.isInteger(j.version)) {
    throw new HeaderError(`header.version must be a uint32, got ${j.version}`);
  }
  if (!Number.isInteger(j.time) || j.time < 0) {
    throw new HeaderError(`header.time must be a uint32, got ${j.time}`);
  }
  if (!Number.isInteger(j.nonce)) {
    throw new HeaderError(`header.nonce must be a uint32, got ${j.nonce}`);
  }
  if (!/^[0-9a-fA-F]{8}$/.test(j.bits)) {
    throw new HeaderError(`header.bits must be 8 hex chars, got ${j.bits}`);
  }
  if (!/^[0-9a-fA-F]{64}$/.test(j.merkleroot)) {
    throw new HeaderError(`header.merkleroot must be 64 hex chars`);
  }
  if (!/^[0-9a-fA-F]{64}$/.test(j.hash)) {
    throw new HeaderError(`header.hash must be 64 hex chars`);
  }

  // The displayed-hex hashes are big-endian; the wire form is the
  // byte-reverse.
  const merkleRoot = hexToBytes(j.merkleroot).reverse();

  let prevHash: Uint8Array;
  if (j.previousblockhash) {
    if (!/^[0-9a-fA-F]{64}$/.test(j.previousblockhash)) {
      throw new HeaderError(`header.previousblockhash must be 64 hex chars`);
    }
    prevHash = hexToBytes(j.previousblockhash).reverse();
  } else {
    if (j.height !== 0) {
      throw new HeaderError(
        `non-genesis header at height ${j.height} has no previousblockhash`,
      );
    }
    prevHash = ZERO32;
  }

  // The compact `bits` field is rendered big-endian-hex by WoC; on the
  // wire we want little-endian uint32 bytes.
  const bitsValue = parseInt(j.bits, 16);
  const out = new Uint8Array(HEADER_SIZE);
  writeU32LE(j.version >>> 0, out, 0);
  out.set(prevHash, 4);
  out.set(merkleRoot, 36);
  writeU32LE(j.time >>> 0, out, 68);
  writeU32LE(bitsValue >>> 0, out, 72);
  writeU32LE(j.nonce >>> 0, out, 76);

  // Self-consistency check: hash the bytes we just built and compare
  // against the JSON's declared hash. A mismatch usually means WoC
  // returned the JSON for a different block than we asked for, or one
  // of the input fields was malformed in a way the regex above didn't
  // catch (e.g. a non-canonical BSV-classic version on a regtest mirror).
  const expectedHash = hexToBytes(j.hash).reverse();
  const actualHash = headerHash(out);
  if (!bytesEqual(expectedHash, actualHash)) {
    throw new HeaderError(
      `WoC header self-check failed at height ${j.height}: ` +
        `declared hash ${j.hash} != recomputed ${bytesToHex(actualHash.slice().reverse())}`,
    );
  }
  return out;
}

// ---------------------------------------------------------------------------
// Validated-header cache (IndexedDB).
//
// The cache is purely an *amortization* optimisation: dropping the DB
// rebuilds from WoC the next time the companion is opened. Every entry
// in the store has been PoW-validated and Merkle-linked back to the
// firmware checkpoint at insert time, so a reader that trusts the
// checkpoint can trust the rows without revalidating.
// ---------------------------------------------------------------------------

export const HEADERS_DB_NAME = "piwallet-companion-headers";
export const HEADERS_DB_VERSION = 1;
export const HEADERS_STORE = "validated-headers";

/**
 * One row in the validated-header cache. Keyed by ``[network, height]``
 * so the mainnet and testnet chains coexist without collision.
 */
export interface CachedHeader {
  network: NetworkT;
  height: number;
  /** Displayed (big-endian) hash hex. */
  hashHex: string;
  /** Displayed (big-endian) merkle root hex. */
  merkleRootHex: string;
  /** 80-byte header bytes, base64-free hex for IndexedDB friendliness. */
  rawHex: string;
  /** Wall-clock timestamp the row was validated and stored. */
  validatedAt: string;
}

export class HeaderCacheError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "HeaderCacheError";
  }
}

function asCacheError(e: unknown, ctx: string): HeaderCacheError {
  const msg = e instanceof Error ? e.message : String(e);
  return new HeaderCacheError(`${ctx}: ${msg}`);
}

function openCacheDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(HEADERS_DB_NAME, HEADERS_DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(HEADERS_STORE)) {
        db.createObjectStore(HEADERS_STORE, {
          keyPath: ["network", "height"],
        });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(asCacheError(req.error, "indexedDB.open"));
    req.onblocked = () =>
      reject(new HeaderCacheError("indexedDB.open: blocked by another tab"));
  });
}

function reqPromise<T>(request: IDBRequest<T>, ctx: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(asCacheError(request.error, ctx));
  });
}

async function withCacheStore<T>(
  mode: IDBTransactionMode,
  fn: (store: IDBObjectStore) => Promise<T> | T,
): Promise<T> {
  const db = await openCacheDb();
  try {
    const tx = db.transaction(HEADERS_STORE, mode);
    const store = tx.objectStore(HEADERS_STORE);
    const result = await Promise.resolve(fn(store));
    return new Promise<T>((resolve, reject) => {
      tx.oncomplete = () => resolve(result);
      tx.onerror = () => reject(asCacheError(tx.error, "transaction"));
      tx.onabort = () =>
        reject(asCacheError(tx.error, "transaction aborted"));
    });
  } finally {
    db.close();
  }
}

/** Look up one cached header (or `null`). */
export async function getCachedHeader(
  network: NetworkT,
  height: number,
): Promise<CachedHeader | null> {
  const out = await withCacheStore("readonly", (store) =>
    reqPromise<CachedHeader | undefined>(
      store.get([network, height]) as IDBRequest<CachedHeader | undefined>,
      "get",
    ),
  );
  return out ?? null;
}

/** Range query: every cached header in `[fromHeight, toHeight]`. */
export async function getCachedHeaderRange(
  network: NetworkT,
  fromHeight: number,
  toHeight: number,
): Promise<CachedHeader[]> {
  if (toHeight < fromHeight) return [];
  const range = IDBKeyRange.bound(
    [network, fromHeight],
    [network, toHeight],
    false,
    false,
  );
  return withCacheStore("readonly", (store) =>
    reqPromise<CachedHeader[]>(
      store.getAll(range) as IDBRequest<CachedHeader[]>,
      "getAll-range",
    ),
  );
}

/**
 * Insert (or overwrite) a batch of validated headers atomically.
 *
 * Caller MUST have already run {@link verifyChain} over the batch
 * against the firmware checkpoint (or against a previously-validated
 * cached entry); the cache itself does NOT re-verify on insert because
 * that would defeat the amortization purpose.
 */
export async function putValidatedHeaders(
  rows: readonly CachedHeader[],
): Promise<void> {
  if (rows.length === 0) return;
  await withCacheStore("readwrite", async (store) => {
    for (const row of rows) {
      await reqPromise(store.put(row), "put");
    }
  });
}

/**
 * Drop the entire validated-header cache. Useful when the firmware
 * checkpoint changes (a stale cache could otherwise be re-anchored to
 * a no-longer-trusted hash) or when the user explicitly requests a
 * full resync from the diagnostics screen.
 */
export async function clearHeaderCache(): Promise<void> {
  await withCacheStore("readwrite", (store) =>
    reqPromise(store.clear(), "clear"),
  );
}

/**
 * Return the highest cached height for ``network`` whose chain links
 * unbroken back to ``fromHeight`` — i.e. the tip up to which the
 * cache is internally consistent. Used by callers that want to know
 * how many headers they still need to fetch from WoC to extend the
 * chain to a desired target height.
 */
export async function getCachedTip(
  network: NetworkT,
  fromHeight: number,
): Promise<{ height: number; hash: Uint8Array } | null> {
  const rows = await getCachedHeaderRange(
    network,
    fromHeight,
    Number.MAX_SAFE_INTEGER,
  );
  if (rows.length === 0) return null;
  rows.sort((a, b) => a.height - b.height);
  let prevHashHex: string | null = null;
  let lastValid: CachedHeader | null = null;
  let expectedHeight = fromHeight;
  for (const row of rows) {
    if (row.height !== expectedHeight) break;
    const parsed = parseHeader(hexToBytes(row.rawHex));
    if (prevHashHex !== null) {
      const got = bytesToHex(parsed.prevHash.slice().reverse());
      if (got !== prevHashHex) break;
    }
    prevHashHex = row.hashHex;
    lastValid = row;
    expectedHeight += 1;
  }
  if (!lastValid) return null;
  return {
    height: lastValid.height,
    hash: hexToBytes(lastValid.hashHex).reverse(),
  };
}

// ---------------------------------------------------------------------------
// Chain assembly: glue between WoC, validation, and the cache.
// ---------------------------------------------------------------------------

/**
 * Minimal interface for the fetch surface ``ensureChain`` needs.
 * Structurally satisfied by `WocClient.getHeaderChain`; accepting it
 * here as an interface keeps `headers.ts` independent of the WoC
 * client and lets tests stub the network with a plain function.
 */
export interface HeaderChainFetcher {
  getHeaderChain(fromHeight: number, count: number): Promise<WocHeaderJson[]>;
}

/**
 * Result of {@link ensureChain}. Heights start at
 * ``checkpoint.height + 1`` and are dense up to and including
 * ``targetHeight``. ``rawHeaders`` contains the 80-byte wire form
 * for each height, ready to splice into an unsigned-proposal
 * envelope; ``merkleRootByHeight`` is the byproduct of the validation
 * walk and lets callers verify Merkle proofs without re-parsing.
 */
export interface EnsuredChain {
  checkpoint: CheckpointHeader;
  rawHeaders: Uint8Array[];
  merkleRootByHeight: Map<number, Uint8Array>;
}

/**
 * Build a validated header chain from the firmware checkpoint up to
 * ``targetHeight``, populating the IndexedDB cache as we go.
 *
 * The function is *idempotent* across runs: a warm cache that
 * already covers the target range short-circuits with zero network
 * traffic, while a cold or partial cache fetches only the missing
 * suffix. Every fetched header is validated against the immediately-
 * preceding one (PoW + linkage); the first fetched header is
 * validated against the highest cached entry, or against the
 * checkpoint if the cache is empty.
 *
 * Throws {@link HeaderError} on any validation failure (and leaves
 * the cache in a consistent state — all rows committed up to the
 * failure point are still anchored to the checkpoint).
 *
 * @param network          which chain ("main" or "test")
 * @param targetHeight     highest block height the caller needs
 * @param fetcher          source of WoC JSON header rows
 * @param chunkSize        how many headers to fetch per WoC call;
 *                         defaults to 100, which keeps each batch
 *                         under a minute even at the documented
 *                         ~3 req/s rate limit.
 * @param now              testable wall-clock; defaults to `Date.now`.
 */
export async function ensureChain(
  network: NetworkT,
  targetHeight: number,
  fetcher: HeaderChainFetcher,
  options: {
    chunkSize?: number;
    now?: () => Date;
  } = {},
): Promise<EnsuredChain> {
  const checkpoint = checkpointFor(network);
  if (!Number.isInteger(targetHeight) || targetHeight < checkpoint.height) {
    throw new HeaderError(
      `targetHeight ${targetHeight} must be an integer >= checkpoint height ${checkpoint.height}`,
    );
  }
  const now = options.now ?? (() => new Date());
  const chunkSize = options.chunkSize ?? 100;
  if (!Number.isInteger(chunkSize) || chunkSize < 1) {
    throw new HeaderError(`chunkSize must be a positive integer`);
  }

  // Read whatever validated suffix the cache already has.
  const cached = await getCachedHeaderRange(
    network,
    checkpoint.height + 1,
    targetHeight,
  );
  cached.sort((a, b) => a.height - b.height);

  let nextHeight = checkpoint.height + 1;
  let expectedPrev = checkpoint.hash;
  const rawHeaders: Uint8Array[] = [];
  const merkleRootByHeight = new Map<number, Uint8Array>();

  for (const row of cached) {
    if (row.height !== nextHeight) break;
    const raw = hexToBytes(row.rawHex);
    if (raw.length !== HEADER_SIZE) break;
    const parsed = parseHeader(raw);
    // A row that no longer chains back to the checkpoint signals a
    // checkpoint rotation: the cache's absolute trust anchor moved
    // out from under it. Fall through to a re-fetch and let
    // putValidatedHeaders overwrite the bad row in place.
    if (!bytesEqual(parsed.prevHash, expectedPrev)) break;
    rawHeaders.push(raw);
    merkleRootByHeight.set(row.height, parsed.merkleRoot);
    expectedPrev = headerHash(raw);
    nextHeight = row.height + 1;
  }

  // Fetch the missing suffix in chunks, validating + caching each
  // batch atomically. Persisting per-chunk caps the maximum cache
  // gap we'd leave behind on a mid-fetch crash.
  while (nextHeight <= targetHeight) {
    const chunkStart = nextHeight;
    const remaining = targetHeight - chunkStart + 1;
    const take = Math.min(chunkSize, remaining);
    const json = await fetcher.getHeaderChain(chunkStart, take);
    if (json.length !== take) {
      throw new HeaderError(
        `expected ${take} headers from ${chunkStart}, got ${json.length}`,
      );
    }
    const newRows: CachedHeader[] = [];
    for (let i = 0; i < json.length; i++) {
      const h = chunkStart + i;
      const row = json[i];
      if (typeof row.height === "number" && row.height !== h) {
        throw new HeaderError(
          `height mismatch: requested ${h}, got ${row.height}`,
        );
      }
      const raw = rawHeaderFromJson({ ...row, height: h });
      const parsed = parseHeader(raw);
      if (!bytesEqual(parsed.prevHash, expectedPrev)) {
        const exp = bytesToHex(expectedPrev.slice().reverse());
        const got = bytesToHex(parsed.prevHash.slice().reverse());
        throw new HeaderError(
          `height ${h}: prev_hash mismatch (expected ${exp}, got ${got})`,
        );
      }
      verifyPow(parsed);
      const hashRaw = headerHash(raw);
      rawHeaders.push(raw);
      merkleRootByHeight.set(h, parsed.merkleRoot);
      newRows.push({
        network,
        height: h,
        hashHex: bytesToHex(hashRaw.slice().reverse()),
        merkleRootHex: bytesToHex(parsed.merkleRoot.slice().reverse()),
        rawHex: bytesToHex(raw),
        validatedAt: now().toISOString(),
      });
      expectedPrev = hashRaw;
    }
    nextHeight = chunkStart + json.length;
    await putValidatedHeaders(newRows);
  }

  return { checkpoint, rawHeaders, merkleRootByHeight };
}

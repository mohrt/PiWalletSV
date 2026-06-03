/**
 * Thin WhatsOnChain (WoC) v1 client.
 *
 * Read-only paths used by the companion to populate the watch-only state
 * of a paired wallet:
 *
 * - `getUnspent(address)`   — UTXOs by P2PKH address.
 * - `getTxHex(txid)`        — raw transaction hex (needed for BEEF assembly).
 * - `getTxProof(txid)`      — Merkle proof + block hash (needed for SPV).
 * - `getHeaderByHash(hash)` — block header (Merkle root anchor).
 * - `getChainInfo()`        — current block height etc.
 *
 * Plus one write path:
 *
 * - `broadcastRaw(hex, knownTxid?)` — POST raw signed tx hex; returns the txid.
 *
 * Network endpoint is configurable. Built-in bases:
 *   - mainnet (default): `https://api.whatsonchain.com/v1/bsv/main`
 *   - testnet:           `https://api.whatsonchain.com/v1/bsv/test`
 *
 * Callers receive the wallet's network from the `xpub_export` envelope
 * and pass `baseUrl: wocBaseForNetwork(network)` so a paired testnet
 * wallet hits TBSV endpoints. The unauthenticated rate limit is
 * ~3 req/s on either base; callers should batch / pace.
 *
 * Design notes:
 *
 * - `fetch` is injectable so tests can stub it without touching the
 *   network. Default is the global `fetch`.
 * - All endpoints return JSON; the wrapper validates shape and surfaces
 *   structured `WocError` instead of leaking raw HTTP details.
 * - Non-2xx responses become `WocError` with HTTP status + endpoint
 *   path; the caller decides whether to retry.
 */

import type { NetworkT } from "./envelope.js";

/** WhatsOnChain BSV mainnet v1 root. */
export const WOC_MAINNET_BASE = "https://api.whatsonchain.com/v1/bsv/main";
/** WhatsOnChain BSV testnet v1 root. */
export const WOC_TESTNET_BASE = "https://api.whatsonchain.com/v1/bsv/test";
/**
 * Backwards-compatible alias for {@link WOC_MAINNET_BASE}. Existing
 * callers that didn't specify a base URL kept hitting mainnet via
 * this constant; that behaviour is preserved.
 */
export const WOC_DEFAULT_BASE = WOC_MAINNET_BASE;

/**
 * Resolve the WoC base URL for a given network. Companion code paths
 * that take a paired wallet should call this with `wallet.network`
 * rather than referencing a constant directly.
 */
export function wocBaseForNetwork(network: NetworkT): string {
  return network === "test" ? WOC_TESTNET_BASE : WOC_MAINNET_BASE;
}

/**
 * Same-origin path used by {@link effectiveWocBase} when the page is
 * served from the Vite dev server. The dev server proxies these prefixes
 * to {@link WOC_MAINNET_BASE} / {@link WOC_TESTNET_BASE} (see
 * `companion/vite.config.ts`).
 */
export const WOC_DEV_PROXY_MAINNET_PATH = "/woc-main";
export const WOC_DEV_PROXY_TESTNET_PATH = "/woc-test";

/**
 * Resolve the WoC base URL the companion should *actually* fetch from.
 *
 * In dev (Vite dev server) the page is loaded over a self-signed
 * HTTPS cert and mobile WebKit refuses cross-origin `fetch()` from
 * such a page — the request fails with status 0 and Safari's generic
 * "Load failed" message even when CORS on the target is wide open.
 * To dodge that, the WoC client uses a *same-origin* path
 * (`/woc-main` / `/woc-test`) and the dev server proxies it to the
 * real WoC base. Production builds (`vite build`, served from a
 * real-cert origin) talk directly to `api.whatsonchain.com`.
 *
 * Tests can pin the branch by passing `options.dev` explicitly;
 * call sites in app code never pass it.
 */
export function effectiveWocBase(
  network: NetworkT,
  options: { dev?: boolean } = {},
): string {
  const dev = options.dev ?? import.meta.env.DEV;
  if (dev) {
    return network === "test"
      ? WOC_DEV_PROXY_TESTNET_PATH
      : WOC_DEV_PROXY_MAINNET_PATH;
  }
  return wocBaseForNetwork(network);
}

/** Public block explorer origins (Next.js app — tx pages are ``/tx/<txid>``). */
export const WOC_EXPLORER_MAIN = "https://whatsonchain.com";
export const WOC_EXPLORER_TEST = "https://test.whatsonchain.com";

/** Human-facing WhatsOnChain transaction page for a txid. */
export function wocExplorerTxUrl(txid: string, network: NetworkT = "main"): string {
  const id = txid.trim().toLowerCase().replace(/^0x/, "");
  const origin = network === "test" ? WOC_EXPLORER_TEST : WOC_EXPLORER_MAIN;
  return `${origin}/tx/${id}`;
}

export interface WocUnspentEntry {
  txid: string;
  vout: number;
  /** Output value in satoshis. */
  sats: number;
  /** Confirmation block height (0 if mempool). */
  height: number;
}

/** One row of a {@link WocClient.getUnspentBatch} response. */
export interface WocBulkUnspentResult {
  address: string;
  utxos: WocUnspentEntry[];
}

/** One tx row from {@link WocClient.getAddressHistoryBatch}. */
export interface WocAddressHistoryEntry {
  txid: string;
  /** Confirmation block height (0 if mempool / unknown). */
  blockHeight: number;
}

/** One row of a {@link WocClient.getAddressHistoryBatch} response. */
export interface WocBulkHistoryResult {
  address: string;
  entries: WocAddressHistoryEntry[];
}

/** Parsed `GET /tx/{txid}` fields used for wallet history deltas. */
export interface WocTxVinRef {
  txid: string;
  vout: number;
  /** Non-empty when this input is a coinbase generation. */
  coinbase?: string;
}

export interface WocTxVoutRef {
  /** Output value in whole BSV (WoC decimal). */
  valueBsv: number;
  address?: string;
}

export interface WocTxDetail {
  txid: string;
  /** Unix timestamp (seconds). 0 if unknown. */
  time: number;
  blockHeight: number;
  vin: WocTxVinRef[];
  vout: WocTxVoutRef[];
}

/**
 * Max addresses per `POST /addresses/unspent` call. WoC documents
 * this as 20 across both mainnet and testnet. Going over yields an
 * HTTP 4xx; the {@link WocClient.getUnspentBatch} method enforces
 * the cap client-side so the error is loud and local.
 */
export const WOC_BULK_BATCH_MAX = 20;

export interface WocTxProof {
  /** Position of the tx within the block's transaction tree. */
  txIndex: number;
  /** Block hash that includes the tx (default `targetType=blockHash`). */
  blockHash: string;
  /**
   * Sibling hashes one per Merkle level (level 0 first). A `"*"` entry is
   * a TSC "duplicate" marker meaning the missing sibling at that level
   * equals the entry directly to its left (BSV/Bitcoin's right-leaning
   * tree fill-up rule). Big-endian hex like WoC emits.
   */
  nodes: string[];
}

export interface WocBlockHeader {
  hash: string;
  height: number;
  merkleroot: string;
  /** UNIX timestamp the miner reported. */
  time: number;
  previousblockhash?: string;
}

/**
 * Raw shape of `GET /block/{hashOrHeight}/header` carrying every
 * field needed to reconstruct the 80-byte wire form. Distinct from
 * {@link WocBlockHeader} (which omits the PoW-relevant `version`,
 * `bits`, `nonce` triple) so type-checkers prevent accidentally
 * mixing the two surfaces — only the chain-fetch path needs the
 * complete shape, and only it can do PoW validation.
 *
 * Defined here rather than in `headers.ts` so call sites that only
 * consume the WoC response don't have to import the SPV machinery,
 * but `rawHeaderFromJson` accepts this same shape via a structural
 * subtype (see {@link "./headers.js".WocHeaderJson}).
 */
export interface WocHeaderJsonShape {
  hash: string;
  height: number;
  /** Little-endian uint32 source value. */
  version: number;
  /** Compact target rendered as 8 hex chars (big-endian). */
  bits: string;
  /** PoW nonce (uint32). */
  nonce: number;
  /** Displayed (big-endian) merkle root hex (64 chars). */
  merkleroot: string;
  /** Miner-reported UNIX timestamp. */
  time: number;
  /** Absent on the genesis block. */
  previousblockhash?: string;
}

export interface WocChainInfo {
  blocks: number;
  bestblockhash: string;
  /** Current chain difficulty target. */
  difficulty?: number;
}

export class WocError extends Error {
  readonly endpoint: string;
  readonly status: number;
  readonly bodySnippet: string;
  constructor(endpoint: string, status: number, message: string, bodySnippet = "") {
    super(`WoC ${status} on ${endpoint}: ${message}`);
    this.name = "WocError";
    this.endpoint = endpoint;
    this.status = status;
    this.bodySnippet = bodySnippet;
  }
}

export type FetchFn = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

/**
 * Default minimum interval between WoC requests, in milliseconds.
 *
 * WoC's documented unauthenticated rate limit is ~3 req/s. We pace at
 * 350 ms (~2.85 req/s) — comfortably under the cap so a single client
 * doing a gap-limit scan + proof-fetch + broadcast doesn't trip the
 * limiter even when the LAN router or another tab is also using WoC.
 *
 * Callers with an `apiKey` can pass a smaller value to use the higher
 * authenticated quota.
 */
export const WOC_DEFAULT_MIN_INTERVAL_MS = 350;

/** Default cap on automatic 429 retries. */
export const WOC_DEFAULT_MAX_RETRIES = 4;

export interface WocClientOptions {
  /** Override base URL (default mainnet). */
  baseUrl?: string;
  /** Injectable fetch for tests. */
  fetch?: FetchFn;
  /** Optional WoC API key sent as `woc-api-key` header. */
  apiKey?: string;
  /**
   * Minimum interval between requests, in milliseconds. Defaults to
   * {@link WOC_DEFAULT_MIN_INTERVAL_MS}. Pass `0` to disable pacing
   * (useful in tests with a stubbed fetch).
   */
  minIntervalMs?: number;
  /**
   * Max automatic retries on HTTP 429 (Too Many Requests). Each retry
   * honours the server's `Retry-After` header if present, otherwise
   * uses an exponential backoff capped at 8 s. Defaults to
   * {@link WOC_DEFAULT_MAX_RETRIES}; set to `0` to surface 429 to the
   * caller immediately.
   */
  maxRetries?: number;
  /** Override `Date.now` for tests. */
  now?: () => number;
  /**
   * Override the sleep primitive for tests. Default uses
   * `setTimeout`. The pacer + 429 backoff both go through this so a
   * test stub of `() => Promise.resolve()` makes both effectively
   * instantaneous.
   */
  sleep?: (ms: number) => Promise<void>;
}

export class WocClient {
  readonly baseUrl: string;
  private readonly _fetch: FetchFn;
  private readonly _apiKey: string | undefined;
  private readonly _minIntervalMs: number;
  private readonly _maxRetries: number;
  private readonly _now: () => number;
  private readonly _sleep: (ms: number) => Promise<void>;

  /**
   * Promise chain used to serialize concurrent callers through the
   * pacer. Each `_paced` call snapshots the current value, appends
   * its own release point, and stores that as the new gate — JS's
   * single-threaded model guarantees the snapshot+assign pair is
   * atomic relative to other callers.
   */
  private _gate: Promise<void> = Promise.resolve();
  /** Wall-clock time of the last *issued* fetch. */
  private _lastRequestAt: number = -Infinity;

  constructor(opts: WocClientOptions = {}) {
    this.baseUrl = (opts.baseUrl ?? WOC_DEFAULT_BASE).replace(/\/+$/, "");
    this._fetch = opts.fetch ?? defaultFetch;
    this._apiKey = opts.apiKey;
    this._minIntervalMs = opts.minIntervalMs ?? WOC_DEFAULT_MIN_INTERVAL_MS;
    this._maxRetries = opts.maxRetries ?? WOC_DEFAULT_MAX_RETRIES;
    this._now = opts.now ?? Date.now;
    this._sleep = opts.sleep ?? defaultSleep;
  }

  /**
   * Serialize a network call behind the pacer. All concurrent
   * callers share the same `_gate` chain so a `Promise.all` of N
   * requests trickles out one-per-`_minIntervalMs` rather than
   * stampeding the API.
   */
  private async _paced<T>(fn: () => Promise<T>): Promise<T> {
    const previous = this._gate;
    const release = previous.then(async () => {
      if (this._minIntervalMs > 0) {
        const elapsed = this._now() - this._lastRequestAt;
        const wait = this._minIntervalMs - elapsed;
        if (wait > 0) await this._sleep(wait);
      }
      this._lastRequestAt = this._now();
    });
    // Swallow errors on the gate so a rejected predecessor doesn't
    // wedge the queue forever; the actual error still surfaces via
    // the `await release` below.
    this._gate = release.catch(() => {});
    await release;
    return fn();
  }

  private async request<T>(
    method: "GET" | "POST",
    path: string,
    body?: unknown,
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const headers: Record<string, string> = {
      Accept: "application/json",
    };
    if (this._apiKey) headers["woc-api-key"] = this._apiKey;
    let init: RequestInit;
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      init = { method, headers, body: JSON.stringify(body) };
    } else {
      init = { method, headers };
    }

    // Retry loop for HTTP 429. Other non-2xx statuses are surfaced
    // immediately (4xx ≠ 429 means the request is malformed, not
    // rate-limited; 5xx could be retried but WoC's 5xx pattern is
    // mostly long outages where a quick retry won't help).
    let attempt = 0;
    while (true) {
      let res: Response;
      try {
        res = await this._paced(() => this._fetch(url, init));
      } catch (e) {
        throw new WocError(path, 0, `network: ${(e as Error).message}`);
      }
      if (res.status === 429 && attempt < this._maxRetries) {
        const wait =
          parseRetryAfter(res, this._now) ??
          Math.min(8000, 500 * 2 ** attempt);
        await this._sleep(wait);
        attempt += 1;
        continue;
      }
      if (!res.ok) {
        const snippet = await safeReadText(res, 240);
        // For 429 specifically, surface a friendlier message so the
        // UI doesn't show a bare "Too Many Requests" string.
        if (res.status === 429) {
          throw new WocError(
            path,
            429,
            `rate limited (gave up after ${attempt} retries)`,
            snippet,
          );
        }
        throw new WocError(path, res.status, res.statusText, snippet);
      }
      const ct = res.headers.get("content-type") ?? "";
      if (ct.includes("application/json")) {
        return (await res.json()) as T;
      }
      // Some endpoints return text/plain (e.g. /tx/{txid}/hex).
      return (await res.text()) as unknown as T;
    }
  }

  /** `GET /address/{address}/unspent`. */
  async getUnspent(address: string): Promise<WocUnspentEntry[]> {
    interface Raw {
      tx_hash: string;
      tx_pos: number;
      value: number;
      height: number;
    }
    const raw = await this.request<Raw[] | { error?: string }>(
      "GET",
      `/address/${encodeURIComponent(address)}/unspent`,
    );
    if (!Array.isArray(raw)) {
      const msg =
        raw && typeof raw === "object" && "error" in raw
          ? String(raw.error)
          : "unexpected shape";
      throw new WocError(
        `/address/${address}/unspent`,
        200,
        `unexpected payload: ${msg}`,
      );
    }
    return raw.map((r) => ({
      txid: r.tx_hash,
      vout: r.tx_pos,
      sats: r.value,
      height: r.height,
    }));
  }

  /**
   * Bulk UTXO lookup — confirmed *and* mempool, merged.
   *
   * Calls both `POST /addresses/confirmed/unspent` and
   * `POST /addresses/unconfirmed/unspent` in parallel and merges
   * results per-address. WoC's older `POST /addresses/unspent`
   * (singular) silently excludes mempool UTXOs, which surfaces as a
   * "balance is 0" bug right after a fresh broadcast — the recipient
   * scan can't see the inbound tx until it confirms, sometimes
   * minutes later. The split endpoints expose mempool entries
   * explicitly; mempool entries get `height = 0` to match the
   * single-address `GET /address/{addr}/unspent` convention the rest
   * of the pipeline already speaks.
   *
   * Accepts up to {@link WOC_BULK_BATCH_MAX} addresses per call and
   * returns one entry per address (in the same order as the input)
   * carrying its merged UTXO list. WoC's per-address `error` field
   * surfaces things like "unable to convert address to scripthash";
   * a non-empty error from either sub-call makes this method throw a
   * {@link WocError} so the caller sees the failure rather than
   * treating an unparseable address as "empty" (which would silently
   * inflate the gap-limit counter).
   *
   * UTXOs flagged `isSpentInMempoolTx` are filtered out — they're
   * already being spent by an in-flight transaction and reusing them
   * would guarantee a double-spend.
   *
   * Used by the gap-limit scanner so a fresh-wallet scan turns 40
   * paced GETs into ~2 paced POST pairs — see {@link scanWalletUtxos}.
   * The two POSTs flow through {@link _paced} so they still respect
   * `_minIntervalMs` against WoC's rate limiter.
   */
  async getUnspentBatch(addresses: string[]): Promise<WocBulkUnspentResult[]> {
    if (addresses.length === 0) return [];
    if (addresses.length > WOC_BULK_BATCH_MAX) {
      throw new WocError(
        "/addresses/unspent",
        0,
        `bulk size ${addresses.length} exceeds max ${WOC_BULK_BATCH_MAX}`,
      );
    }
    interface RawUtxoEntry {
      tx_hash: string;
      tx_pos: number;
      value: number;
      /** Confirmed entries always have a positive height; the
       * unconfirmed endpoint omits this field — we synthesize 0. */
      height?: number;
      isSpentInMempoolTx?: boolean;
    }
    interface RawAddressRow {
      address?: string;
      script?: string;
      result?: RawUtxoEntry[];
      error?: string;
    }
    const fetchOne = async (path: string): Promise<RawAddressRow[]> => {
      const raw = await this.request<RawAddressRow[] | { error?: string }>(
        "POST",
        path,
        { addresses },
      );
      if (!Array.isArray(raw)) {
        const msg =
          raw && typeof raw === "object" && "error" in raw
            ? String(raw.error)
            : "unexpected shape";
        throw new WocError(path, 200, `unexpected payload: ${msg}`);
      }
      const failed = raw.find(
        (e) => typeof e.error === "string" && e.error.length > 0,
      );
      if (failed) {
        throw new WocError(
          path,
          200,
          `address ${failed.address ?? "?"} failed: ${failed.error}`,
        );
      }
      return raw;
    };

    const [confirmedRows, unconfirmedRows] = await Promise.all([
      fetchOne("/addresses/confirmed/unspent"),
      fetchOne("/addresses/unconfirmed/unspent"),
    ]);

    // Merge per-address. Map keyed by address, seeded with empty
    // lists so addresses with no UTXOs still get a row in the
    // output (preserves the contract: one output row per input
    // address, in input order).
    const byAddress = new Map<string, WocUnspentEntry[]>();
    for (const a of addresses) byAddress.set(a, []);
    const upsert = (list: WocUnspentEntry[], entry: WocUnspentEntry): void => {
      const idx = list.findIndex(
        (u) => u.txid === entry.txid && u.vout === entry.vout,
      );
      if (idx === -1) {
        list.push(entry);
        return;
      }
      // WoC can surface the same outpoint on both confirmed and
      // unconfirmed lists during propagation; keep the higher height.
      if (entry.height > list[idx]!.height) {
        list[idx] = entry;
      }
    };
    const merge = (rows: RawAddressRow[]): void => {
      for (const row of rows) {
        if (!row.address) continue;
        const list = byAddress.get(row.address);
        if (!list) continue;
        for (const u of row.result ?? []) {
          // Already-being-spent UTXOs are unsafe to count: balance
          // would be inflated and any selector that picks them would
          // produce a double-spend the moment it's broadcast.
          if (u.isSpentInMempoolTx) continue;
          upsert(list, {
            txid: u.tx_hash,
            vout: u.tx_pos,
            sats: u.value,
            height: u.height ?? 0,
          });
        }
      }
    };
    merge(confirmedRows);
    merge(unconfirmedRows);

    return addresses.map((address) => ({
      address,
      utxos: byAddress.get(address) ?? [],
    }));
  }

  /**
   * Bulk confirmed + unconfirmed tx history lookup.
   *
   * `POST /addresses/history/all` returns tx hashes + heights per address.
   * Unlike Bitails, WoC does not include net satoshi deltas — callers that
   * need +/- amounts must fetch raw txs separately.
   */
  async getAddressHistoryBatch(
    addresses: string[],
  ): Promise<WocBulkHistoryResult[]> {
    if (addresses.length === 0) return [];
    if (addresses.length > WOC_BULK_BATCH_MAX) {
      throw new WocError(
        "/addresses/history/all",
        0,
        `bulk size ${addresses.length} exceeds max ${WOC_BULK_BATCH_MAX}`,
      );
    }
    interface RawHistoryEntry {
      tx_hash: string;
      height?: number;
    }
    interface RawHistorySection {
      result?: RawHistoryEntry[];
      error?: string;
    }
    interface RawHistoryRow {
      address?: string;
      confirmed?: RawHistorySection;
      unconfirmed?: RawHistorySection;
      error?: string;
    }
    const raw = await this.request<RawHistoryRow[] | { error?: string }>(
      "POST",
      "/addresses/history/all",
      { addresses },
    );
    if (!Array.isArray(raw)) {
      const msg =
        raw && typeof raw === "object" && "error" in raw
          ? String(raw.error)
          : "unexpected shape";
      throw new WocError("/addresses/history/all", 200, `unexpected payload: ${msg}`);
    }
    const failed = raw.find(
      (e) =>
        (typeof e.error === "string" && e.error.length > 0) ||
        (typeof e.confirmed?.error === "string" && e.confirmed.error.length > 0) ||
        (typeof e.unconfirmed?.error === "string" && e.unconfirmed.error.length > 0),
    );
    if (failed) {
      const msg =
        failed.error ||
        failed.confirmed?.error ||
        failed.unconfirmed?.error ||
        "unknown";
      throw new WocError(
        "/addresses/history/all",
        200,
        `address ${failed.address ?? "?"} failed: ${msg}`,
      );
    }
    const byAddress = new Map<string, WocAddressHistoryEntry[]>();
    for (const a of addresses) byAddress.set(a, []);
    const upsert = (
      list: WocAddressHistoryEntry[],
      txid: string,
      blockHeight: number,
    ): void => {
      const existing = list.find((e) => e.txid === txid);
      if (!existing) {
        list.push({ txid, blockHeight });
        return;
      }
      if (blockHeight > existing.blockHeight) {
        existing.blockHeight = blockHeight;
      }
    };
    for (const row of raw) {
      if (!row.address) continue;
      const list = byAddress.get(row.address);
      if (!list) continue;
      for (const section of [row.confirmed, row.unconfirmed]) {
        for (const h of section?.result ?? []) {
          if (!h.tx_hash) continue;
          upsert(list, h.tx_hash, h.height ?? 0);
        }
      }
    }
    return addresses.map((address) => ({
      address,
      entries: byAddress.get(address) ?? [],
    }));
  }

  /** `GET /tx/{txid}` — decoded tx with vout addresses for history deltas. */
  async getTxDetail(txid: string): Promise<WocTxDetail> {
    interface RawVin {
      txid?: string;
      vout?: number;
      coinbase?: string;
    }
    interface RawVout {
      value?: number;
      scriptPubKey?: { addresses?: string[] };
    }
    interface RawTx {
      txid?: string;
      time?: number;
      blockheight?: number;
      blocktime?: number;
      vin?: RawVin[];
      vout?: RawVout[];
    }
    const raw = await this.request<RawTx>(
      "GET",
      `/tx/${encodeURIComponent(txid)}`,
    );
    return {
      txid: raw.txid ?? txid,
      time: raw.blocktime ?? raw.time ?? 0,
      blockHeight: raw.blockheight ?? 0,
      vin: (raw.vin ?? []).map((v) => ({
        txid: v.txid ?? "",
        vout: v.vout ?? 0,
        coinbase: v.coinbase,
      })),
      vout: (raw.vout ?? []).map((v) => ({
        valueBsv: v.value ?? 0,
        address: v.scriptPubKey?.addresses?.[0],
      })),
    };
  }

  /** `GET /tx/{txid}/hex` — raw transaction hex string. */
  async getTxHex(txid: string): Promise<string> {
    const raw = await this.request<string>(
      "GET",
      `/tx/${encodeURIComponent(txid)}/hex`,
    );
    if (typeof raw !== "string" || !/^[0-9a-fA-F]+$/.test(raw.trim())) {
      throw new WocError(
        `/tx/${txid}/hex`,
        200,
        `unexpected payload (not hex)`,
      );
    }
    return raw.trim();
  }

  /**
   * `GET /tx/{txid}/proof/tsc` — TSC (BRC-10) Merkle proof.
   *
   * Returns `null` when the tx is unconfirmed (WoC 404). The returned
   * shape is normalized; callers should hand it to
   * `proof-fetcher.tscProofToMerklePath` which converts it to a
   * `@bsv/sdk` MerklePath.
   */
  async getTxProof(txid: string): Promise<WocTxProof | null> {
    interface RawProof {
      index?: number;
      txOrId?: string;
      target?: string;
      targetType?: string;
      nodes?: string[];
    }
    let payload: RawProof | RawProof[];
    try {
      payload = await this.request<RawProof | RawProof[]>(
        "GET",
        `/tx/${encodeURIComponent(txid)}/proof/tsc`,
      );
    } catch (e) {
      // WoC returns 404 when the tx is still in the mempool / unconfirmed.
      if (e instanceof WocError && e.status === 404) return null;
      throw e;
    }
    const raw = Array.isArray(payload) ? payload[0] : payload;
    if (
      !raw ||
      typeof raw.index !== "number" ||
      typeof raw.target !== "string" ||
      !Array.isArray(raw.nodes)
    ) {
      return null;
    }
    // `targetType` defaults to "blockHash" when omitted (TSC spec). We only
    // support blockHash here — caller resolves the merkleroot via getHeader.
    if (raw.targetType !== undefined && raw.targetType !== "blockHash") {
      throw new WocError(
        `/tx/${txid}/proof/tsc`,
        200,
        `unsupported targetType: ${raw.targetType} (only blockHash)`,
      );
    }
    return {
      txIndex: raw.index,
      blockHash: raw.target,
      nodes: raw.nodes,
    };
  }

  /**
   * `GET /block/{hashOrHeight}/header` — block header by hash or height.
   *
   * Returns only the 80-byte header fields parsed as JSON (no tx list).
   * The endpoint accepts both a 64-char block hash *or* a decimal height
   * string. We use it with hashes throughout the SPV pipeline because
   * TSC proofs carry `target: blockHash`.
   */
  async getHeaderByHash(hash: string): Promise<WocBlockHeader> {
    interface Raw {
      hash: string;
      height: number;
      merkleroot: string;
      time: number;
      previousblockhash?: string;
    }
    const raw = await this.request<Raw>(
      "GET",
      `/block/${encodeURIComponent(hash)}/header`,
    );
    return {
      hash: raw.hash,
      height: raw.height,
      merkleroot: raw.merkleroot,
      time: raw.time,
      previousblockhash: raw.previousblockhash,
    };
  }

  /**
   * `GET /block/{height}/header` — same endpoint, addressed by height.
   *
   * Returns the *full* JSON body so callers can reconstruct the 80-byte
   * raw wire form locally (see {@link rawHeaderFromJson}). The fields
   * surfaced are the seven that go into the canonical serialization
   * plus the `hash` for self-consistency checks.
   */
  async getHeaderJsonByHeight(height: number): Promise<WocHeaderJsonShape> {
    if (!Number.isInteger(height) || height < 0) {
      throw new WocError(
        `/block/${height}/header`,
        0,
        `height must be a non-negative integer, got ${height}`,
      );
    }
    return this.request<WocHeaderJsonShape>(
      "GET",
      `/block/${encodeURIComponent(String(height))}/header`,
    );
  }

  /**
   * Fetch a contiguous sequence of headers `[fromHeight, fromHeight+count)`
   * via the per-height JSON endpoint, returning each as a 7-field JSON
   * record.
   *
   * WoC has bulk binary endpoints (`/block/headers/latest?count=N`,
   * `/block/headers/resources`) that are more efficient for very long
   * ranges, but those return only the latest N (≤100) blocks or
   * pre-baked 10k-header bundles, neither of which lines up with the
   * arbitrary `[checkpoint, recent-tx-block]` window the SPV pipeline
   * needs. The per-height JSON path is universal and threads through
   * the same `_paced` rate-limiter as everything else, so a cold sync
   * trickles out at the documented ~3 req/s and a warm cache resync
   * (typical case) is just a handful of fetches at the top.
   *
   * Each entry is returned in its source JSON form; the caller is
   * expected to run {@link rawHeaderFromJson} (which validates field
   * shape and recomputes the declared hash) before treating the bytes
   * as authoritative.
   */
  async getHeaderChain(
    fromHeight: number,
    count: number,
  ): Promise<WocHeaderJsonShape[]> {
    if (!Number.isInteger(fromHeight) || fromHeight < 0) {
      throw new WocError(
        "/block/header/chain",
        0,
        `fromHeight must be a non-negative integer, got ${fromHeight}`,
      );
    }
    if (!Number.isInteger(count) || count < 0) {
      throw new WocError(
        "/block/header/chain",
        0,
        `count must be a non-negative integer, got ${count}`,
      );
    }
    const out: WocHeaderJsonShape[] = [];
    for (let i = 0; i < count; i++) {
      const h = fromHeight + i;
      const row = await this.getHeaderJsonByHeight(h);
      // WoC indexes headers by hash internally; if the height in the
      // returned record does not match what we asked for, it's a bug
      // in the upstream mirror, not a transient error worth retrying.
      if (typeof row.height === "number" && row.height !== h) {
        throw new WocError(
          `/block/${h}/header`,
          200,
          `WoC returned header at height ${row.height}, asked for ${h}`,
        );
      }
      out.push(row);
    }
    return out;
  }

  /** `GET /chain/info` — current best block etc. */
  async getChainInfo(): Promise<WocChainInfo> {
    interface Raw {
      blocks: number;
      bestblockhash: string;
      difficulty?: number;
    }
    const raw = await this.request<Raw>("GET", "/chain/info");
    return {
      blocks: raw.blocks,
      bestblockhash: raw.bestblockhash,
      difficulty: raw.difficulty,
    };
  }

  /** `POST /tx/raw` — broadcast a raw signed tx. Returns the txid. */
  async broadcastRaw(rawHex: string, knownTxid?: string): Promise<string> {
    if (!/^[0-9a-fA-F]+$/.test(rawHex) || rawHex.length % 2 !== 0) {
      throw new WocError("/tx/raw", 0, "rawHex must be even-length hex");
    }
    // WoC returns the txid as a quoted JSON string.
    try {
      const res = await this.request<string>("POST", "/tx/raw", { txhex: rawHex });
      if (typeof res !== "string") {
        throw new WocError("/tx/raw", 200, `unexpected broadcast response`);
      }
      return res.replace(/^"|"$/g, "").trim();
    } catch (e) {
      // Re-broadcasting the same signed tx is idempotent — the tx is
      // already propagating. Treat as success when we know the txid.
      if (
        knownTxid &&
        e instanceof WocError &&
        isAlreadyInMempoolError(e)
      ) {
        return knownTxid;
      }
      throw e;
    }
  }
}

/** True when WoC rejected a broadcast because this exact tx is already known. */
export function isAlreadyInMempoolError(e: WocError): boolean {
  const text = `${e.message} ${e.bodySnippet}`.toLowerCase();
  return (
    text.includes("already in the mempool") ||
    text.includes("txn-already-in-mempool") ||
    text.includes("transaction already in the mempool")
  );
}

function defaultFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  if (typeof fetch === "undefined") {
    throw new WocError(
      String(input),
      0,
      "no global fetch available; pass `fetch` via WocClientOptions",
    );
  }
  return fetch(input, init);
}

async function safeReadText(res: Response, max: number): Promise<string> {
  try {
    const text = await res.text();
    return text.length > max ? `${text.slice(0, max)}…` : text;
  } catch {
    return "";
  }
}

/**
 * Parse an HTTP `Retry-After` header into a wait duration in
 * milliseconds. Per RFC 7231 the header may be either an integer
 * number of seconds or an HTTP-date; we support both. A missing,
 * malformed, or non-positive value returns `null` so the caller can
 * fall back to its own backoff schedule.
 *
 * The result is capped at 60 s — Cloudflare in particular sometimes
 * sets a very long `Retry-After` on extended outages, and we'd
 * rather give up after our `maxRetries` budget than block the UI for
 * minutes.
 */
function parseRetryAfter(res: Response, now: () => number): number | null {
  const raw = res.headers.get("retry-after");
  if (!raw) return null;
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const seconds = Number(trimmed);
  if (Number.isFinite(seconds) && seconds > 0) {
    return Math.min(60_000, Math.round(seconds * 1000));
  }
  const dateMs = Date.parse(trimmed);
  if (!Number.isNaN(dateMs)) {
    const wait = dateMs - now();
    if (wait > 0) return Math.min(60_000, wait);
  }
  return null;
}

function defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Thin Bitails (api.bitails.io) BSV client.
 *
 * Used by the companion for features WoC doesn't offer:
 *   - Transaction history with inline sat amounts (receive / send delta)
 *   - Bulk address queries with no hard 20-address cap
 *
 * All other data (UTXOs for coin selection, SPV proofs, fee rates,
 * broadcast) continues to go through {@link WocClient} in `woc.ts`.
 *
 * Bitails free tier: 10 req/s, 1 000 req/day.
 * We pace at 150 ms (~6.7 req/s) to leave headroom.
 *
 * Design mirrors `woc.ts`:
 *   - `fetch` is injectable so tests can stub it without network I/O.
 *   - Non-2xx responses become `BitailsError` (status + bodySnippet).
 *   - 429 is retried with exponential backoff up to `maxRetries` times.
 *   - The `_paced` gate serialises concurrent callers.
 */

import type { NetworkT } from "./envelope.js";

export const BITAILS_MAINNET_BASE = "https://api.bitails.io";
export const BITAILS_TESTNET_BASE = "https://test.bitails.io";

/**
 * Same-origin path used when the companion is served from the Vite
 * dev server (see `effectiveBitailsBase`).
 */
export const BITAILS_DEV_PROXY_PATH = "/bitails";

/**
 * Same-origin path used in production (CloudFront behavior that proxies
 * test.bitails.io and injects Access-Control-Allow-Origin: *).
 * test.bitails.io does not send CORS headers itself, so direct browser
 * fetch() from a custom domain is blocked; routing through CloudFront
 * sidesteps that without exposing any credentials.
 */
export const BITAILS_TESTNET_PROXY_PATH = "/bitails-test";

export function bitailsBaseForNetwork(network: NetworkT): string {
  return network === "test" ? BITAILS_TESTNET_BASE : BITAILS_MAINNET_BASE;
}

/**
 * Resolve the Bitails base URL the companion should fetch from.
 *
 * - Dev + mainnet  → Vite proxy `/bitails`  (avoids self-signed-cert CORS)
 * - Dev + testnet  → direct `test.bitails.io` (rare; acceptable in dev)
 * - Prod + mainnet → direct `api.bitails.io`  (CORS headers present)
 * - Prod + testnet → CloudFront proxy `/bitails-test` (injects CORS header)
 */
export function effectiveBitailsBase(
  network: NetworkT,
  options: { dev?: boolean } = {},
): string {
  const dev = options.dev ?? import.meta.env.DEV;
  if (dev && network === "main") return BITAILS_DEV_PROXY_PATH;
  if (!dev && network === "test") return BITAILS_TESTNET_PROXY_PATH;
  return bitailsBaseForNetwork(network);
}

// ---------------------------------------------------------------------------
// Response shapes
// ---------------------------------------------------------------------------

/** One entry from `POST /address/balance/multi/separate`. */
export interface BitailsAddressBalance {
  address: string;
  confirmed: number;
  unconfirmed: number;
  total: number;
}

/** One page of history from `POST /address/history/multi`. */
export interface BitailsHistoryEntry {
  /**
   * txid (note: Bitails may return it as `txHash` or `tx_hash`
   * depending on endpoint version — we normalise in the client).
   */
  txid: string;
  /** Unix timestamp (seconds). 0 if unconfirmed. */
  timestamp: number;
  /** Block height; 0 if unconfirmed. */
  blockHeight: number;
  /**
   * Net satoshi change for the queried address in this tx.
   * Positive = received, negative = sent.
   */
  deltaSats: number;
}

/** Raw shape returned by `POST /address/history/multi`. */
interface BitailsHistoryRaw {
  address: string;
  /** Cursor for the next page (`null` when exhausted). */
  pgkey?: string | null;
  history: Array<{
    txHash?: string;
    txid?: string;
    timestamp?: number;
    blockTimestamp?: number;
    blockHeight?: number;
    height?: number;
    satoshis?: number;
    value?: number;
  }>;
}

export interface BitailsHistoryResult {
  address: string;
  entries: BitailsHistoryEntry[];
  /** Cursor for the next page; `null` when all pages consumed. */
  nextCursor: string | null;
}

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

export class BitailsError extends Error {
  readonly endpoint: string;
  readonly status: number;
  readonly bodySnippet: string;
  constructor(endpoint: string, status: number, message: string, bodySnippet = "") {
    super(`Bitails ${status} on ${endpoint}: ${message}`);
    this.name = "BitailsError";
    this.endpoint = endpoint;
    this.status = status;
    this.bodySnippet = bodySnippet;
  }
}

// ---------------------------------------------------------------------------
// Client options
// ---------------------------------------------------------------------------

export type FetchFn = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export const BITAILS_DEFAULT_MIN_INTERVAL_MS = 150; // ~6.7 req/s
export const BITAILS_DEFAULT_MAX_RETRIES = 3;

/** Max addresses per bulk call (Bitails does not enforce a hard cap but we
 *  batch at 20 for safety and to keep request sizes reasonable). */
export const BITAILS_BULK_BATCH_MAX = 20;

export interface BitailsClientOptions {
  baseUrl?: string;
  fetch?: FetchFn;
  apiKey?: string;
  minIntervalMs?: number;
  maxRetries?: number;
  now?: () => number;
  sleep?: (ms: number) => Promise<void>;
}

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

export class BitailsClient {
  readonly baseUrl: string;
  private readonly _fetch: FetchFn;
  private readonly _apiKey: string | undefined;
  private readonly _minIntervalMs: number;
  private readonly _maxRetries: number;
  private readonly _now: () => number;
  private readonly _sleep: (ms: number) => Promise<void>;
  private _gate: Promise<void> = Promise.resolve();
  private _lastRequestAt: number = -Infinity;

  constructor(opts: BitailsClientOptions = {}) {
    this.baseUrl = (opts.baseUrl ?? BITAILS_MAINNET_BASE).replace(/\/+$/, "");
    this._fetch = opts.fetch ?? defaultFetch;
    this._apiKey = opts.apiKey;
    this._minIntervalMs = opts.minIntervalMs ?? BITAILS_DEFAULT_MIN_INTERVAL_MS;
    this._maxRetries = opts.maxRetries ?? BITAILS_DEFAULT_MAX_RETRIES;
    this._now = opts.now ?? Date.now;
    this._sleep = opts.sleep ?? defaultSleep;
  }

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
    if (this._apiKey) headers["apikey"] = this._apiKey;
    let init: RequestInit;
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      init = { method, headers, body: JSON.stringify(body) };
    } else {
      init = { method, headers };
    }

    let attempt = 0;
    while (true) {
      let res: Response;
      try {
        res = await this._paced(() => this._fetch(url, init));
      } catch (e) {
        throw new BitailsError(path, 0, `network: ${(e as Error).message}`);
      }
      if (res.status === 429 && attempt < this._maxRetries) {
        const retryAfter = res.headers.get("Retry-After");
        const wait = retryAfter
          ? Math.max(0, parseFloat(retryAfter) * 1000)
          : Math.min(8000, 500 * 2 ** attempt);
        await this._sleep(wait);
        attempt += 1;
        continue;
      }
      if (!res.ok) {
        const snippet = await safeReadText(res, 240);
        throw new BitailsError(path, res.status, res.statusText, snippet);
      }
      return (await res.json()) as T;
    }
  }

  /**
   * `POST /address/balance/multi/separate`
   * Returns per-address confirmed + unconfirmed + total balances.
   * Batch up to {@link BITAILS_BULK_BATCH_MAX} addresses per call.
   */
  async getBalanceBatch(addresses: string[]): Promise<BitailsAddressBalance[]> {
    if (addresses.length === 0) return [];
    if (addresses.length > BITAILS_BULK_BATCH_MAX) {
      throw new BitailsError(
        "/address/balance/multi/separate",
        0,
        `batch size ${addresses.length} exceeds max ${BITAILS_BULK_BATCH_MAX}`,
      );
    }
    const raw = await this.request<BitailsAddressBalance[]>(
      "POST",
      "/address/balance/multi/separate",
      { addresses },
    );
    return raw;
  }

  /**
   * `POST /address/history/multi`
   * Fetches paginated tx history for multiple addresses.
   * Each entry includes the net sat delta for that address.
   *
   * Pass `pgkey` to continue a previous page (cursor from
   * `BitailsHistoryResult.nextCursor`).
   */
  async getHistoryBatch(
    addresses: string[],
    pgkey?: string,
  ): Promise<BitailsHistoryResult[]> {
    if (addresses.length === 0) return [];
    const payload: Record<string, unknown> = { addresses, limit: 50 };
    if (pgkey) payload.pgkey = pgkey;
    const raw = await this.request<BitailsHistoryRaw[]>(
      "POST",
      "/address/history/multi",
      payload,
    );
    return raw.map((r) => ({
      address: r.address,
      nextCursor: r.pgkey ?? null,
      entries: (r.history ?? []).map((h) => ({
        txid: (h.txHash ?? h.txid ?? ""),
        timestamp: h.timestamp ?? h.blockTimestamp ?? 0,
        blockHeight: h.blockHeight ?? h.height ?? 0,
        deltaSats: h.satoshis ?? h.value ?? 0,
      })),
    }));
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function defaultFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  if (typeof fetch === "undefined") {
    throw new BitailsError(
      String(input),
      0,
      "no global fetch available; pass `fetch` via BitailsClientOptions",
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

function defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

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
export const BITAILS_TESTNET_BASE = "https://test-api.bitails.io";

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
 * - Dev + mainnet  → Vite proxy `/bitails`            (avoids self-signed-cert CORS)
 * - Dev + testnet  → Vite proxy `/bitails-test`      (test-api lacks CORS for localhost)
 * - Prod + mainnet → direct `api.bitails.io`           (CORS headers present)
 * - Prod + testnet → CloudFront proxy `/bitails-test`  (injects CORS headers on ALL
 *                    responses, including 504s from test-api.bitails.io which omits
 *                    CORS headers on error responses and would block the browser)
 *
 * Transaction history on testnet uses WhatsOnChain instead of Bitails — see
 * {@link fetchWalletHistory} in `history.ts`. Bitails' testnet API is frequently
 * down; WoC returns txid + height (no sat deltas).
 */
export function effectiveBitailsBase(
  network: NetworkT,
  options: { dev?: boolean } = {},
): string {
  const dev = options.dev ?? import.meta.env.DEV;
  if (dev && network === "main") return BITAILS_DEV_PROXY_PATH;
  if (dev && network === "test") return BITAILS_TESTNET_PROXY_PATH;
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

/**
 * One entry from `POST /address/history/multi`.
 *
 * The endpoint returns a **combined flat list** across all queried
 * addresses — there is no per-address grouping. `deltaSats` is the net
 * satoshi change across all queried addresses for this tx:
 *   deltaSats = outputSatoshis - inputSatoshis
 * Positive = net receive, negative = net send.
 */
export interface BitailsHistoryEntry {
  txid: string;
  /** Unix timestamp (seconds). 0 if unconfirmed. */
  timestamp: number;
  /** Block height; 0 if unconfirmed. */
  blockHeight: number;
  /**
   * Net satoshi change across all queried addresses in this tx.
   * Positive = received, negative = sent.
   */
  deltaSats: number;
}

/** Raw shape of each item in the flat array from `POST /address/history/multi`. */
interface BitailsHistoryMultiRaw {
  txid: string;
  inputSatoshis: number;
  outputSatoshis: number;
  /** Unix timestamp (seconds). */
  time: number;
  blockheight: number;
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
   * Returns the combined transaction history across all queried addresses
   * as a flat array — entries are NOT grouped per address.
   *
   * Pagination is offset-based: pass `from` to skip already-fetched entries.
   * `limit` and `from` are query parameters, not body fields.
   *
   * `deltaSats = outputSatoshis − inputSatoshis` per entry (positive = receive).
   */
  async getHistoryBatch(
    addresses: string[],
    opts: { limit?: number; from?: number } = {},
  ): Promise<BitailsHistoryEntry[]> {
    if (addresses.length === 0) return [];
    const params = new URLSearchParams();
    params.set("limit", String(opts.limit ?? 100));
    if (opts.from) params.set("from", String(opts.from));
    const raw = await this.request<BitailsHistoryMultiRaw[]>(
      "POST",
      `/address/history/multi?${params.toString()}`,
      { addresses },
    );
    return (raw ?? []).map((h) => ({
      txid: h.txid ?? "",
      timestamp: h.time ?? 0,
      blockHeight: h.blockheight ?? 0,
      deltaSats: (h.outputSatoshis ?? 0) - (h.inputSatoshis ?? 0),
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

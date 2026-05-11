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
 * - `broadcastRaw(hex)`     — POST raw signed tx hex; returns the txid.
 *
 * Network endpoint is configurable but defaults to public BSV mainnet
 * (`https://api.whatsonchain.com/v1/bsv/main`). The unauthenticated rate
 * limit is ~3 req/s; callers should batch / pace.
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

export const WOC_DEFAULT_BASE = "https://api.whatsonchain.com/v1/bsv/main";

export interface WocUnspentEntry {
  txid: string;
  vout: number;
  /** Output value in satoshis. */
  sats: number;
  /** Confirmation block height (0 if mempool). */
  height: number;
}

export interface WocTxProof {
  /** Block hash that includes the tx. */
  blockHash: string;
  /** Merkle branches needed to anchor `txid` -> `merkleRoot` (hex, big-endian). */
  branches: { hash: string; pos: "L" | "R" }[];
  /** The block's merkle root (hex). */
  merkleRoot: string;
  /** Optional: position of `txid` within the block's tx tree. */
  txIndex?: number;
}

export interface WocBlockHeader {
  hash: string;
  height: number;
  merkleroot: string;
  /** UNIX timestamp the miner reported. */
  time: number;
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

export interface WocClientOptions {
  /** Override base URL (default mainnet). */
  baseUrl?: string;
  /** Injectable fetch for tests. */
  fetch?: FetchFn;
  /** Optional WoC API key sent as `woc-api-key` header. */
  apiKey?: string;
}

export class WocClient {
  readonly baseUrl: string;
  private readonly _fetch: FetchFn;
  private readonly _apiKey: string | undefined;

  constructor(opts: WocClientOptions = {}) {
    this.baseUrl = (opts.baseUrl ?? WOC_DEFAULT_BASE).replace(/\/+$/, "");
    this._fetch = opts.fetch ?? defaultFetch;
    this._apiKey = opts.apiKey;
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
    let res: Response;
    try {
      res = await this._fetch(url, init);
    } catch (e) {
      throw new WocError(path, 0, `network: ${(e as Error).message}`);
    }
    if (!res.ok) {
      const snippet = await safeReadText(res, 240);
      throw new WocError(path, res.status, res.statusText, snippet);
    }
    const ct = res.headers.get("content-type") ?? "";
    if (ct.includes("application/json")) {
      return (await res.json()) as T;
    }
    // Some endpoints return text/plain (e.g. /tx/{txid}/hex).
    return (await res.text()) as unknown as T;
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

  /** `GET /tx/{txid}/proof` — TSC-format Merkle proof. */
  async getTxProof(txid: string): Promise<WocTxProof | null> {
    interface RawProof {
      blockHash?: string;
      branches?: { hash: string; pos: string }[];
      merkleRoot?: string;
      txOrId?: string;
      index?: number;
      // Some shapes return an error-like object.
      error?: string;
    }
    let payload: RawProof | RawProof[];
    try {
      payload = await this.request<RawProof | RawProof[]>(
        "GET",
        `/tx/${encodeURIComponent(txid)}/proof`,
      );
    } catch (e) {
      // WoC returns 404 when the tx is still in the mempool / unconfirmed.
      if (e instanceof WocError && e.status === 404) return null;
      throw e;
    }
    const raw = Array.isArray(payload) ? payload[0] : payload;
    if (!raw || !raw.blockHash || !raw.branches || !raw.merkleRoot) {
      return null;
    }
    return {
      blockHash: raw.blockHash,
      branches: raw.branches.map((b) => ({
        hash: b.hash,
        pos: b.pos === "L" ? "L" : "R",
      })),
      merkleRoot: raw.merkleRoot,
      txIndex: typeof raw.index === "number" ? raw.index : undefined,
    };
  }

  /** `GET /block/hash/{hash}/header`. */
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
      `/block/hash/${encodeURIComponent(hash)}/header`,
    );
    return {
      hash: raw.hash,
      height: raw.height,
      merkleroot: raw.merkleroot,
      time: raw.time,
      previousblockhash: raw.previousblockhash,
    };
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
  async broadcastRaw(rawHex: string): Promise<string> {
    if (!/^[0-9a-fA-F]+$/.test(rawHex) || rawHex.length % 2 !== 0) {
      throw new WocError("/tx/raw", 0, "rawHex must be even-length hex");
    }
    // WoC returns the txid as a quoted JSON string.
    const res = await this.request<string>("POST", "/tx/raw", { txhex: rawHex });
    if (typeof res !== "string") {
      throw new WocError("/tx/raw", 200, `unexpected broadcast response`);
    }
    return res.replace(/^"|"$/g, "").trim();
  }
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

/**
 * Wallet transaction history fetcher.
 *
 * Uses the Bitails `POST /address/history/multi` endpoint, which returns
 * the net satoshi delta per tx per address — so we can tell a receive
 * (+sats) from a send (-sats) without fetching the full raw tx.
 *
 * Strategy:
 *   1. Derive receive + change addresses up to the gap-walk range from
 *      the most recent UTXO scan snapshot (`stoppedAt`), plus look-ahead.
 *   2. Batch those addresses into `BITAILS_BULK_BATCH_MAX`-address calls
 *      to `getHistoryBatch`.
 *   3. Merge all per-address entries, aggregate by txid (same tx can
 *      touch multiple addresses), deduplicate, sort by blockHeight desc.
 *   4. Persist the result on the WalletRecord.
 *
 * WoC rate-limit note: this module calls Bitails, not WoC, so it does
 * NOT consume WoC quota and can run in parallel with the UTXO scan.
 */

import {
  CHANGE_BRANCH,
  RECEIVE_BRANCH,
  deriveAddress,
} from "./derive.js";
import type { NetworkT } from "./envelope.js";
import {
  BITAILS_BULK_BATCH_MAX,
  type BitailsHistoryEntry,
  type BitailsClient,
} from "./bitails.js";
import { HISTORY_PAGE_SIZE, MAX_HISTORY_ENTRIES } from "./config.js";
import { DEFAULT_GAP_LIMIT } from "./utxo.js";
import { type WocClient, type WocTxDetail } from "./woc.js";

export interface WalletTxEntry {
  txid: string;
  /** Unix timestamp (seconds). 0 = unconfirmed or unknown. */
  timestamp: number;
  /** Block height (0 = unconfirmed). */
  blockHeight: number;
  /**
   * Net satoshi change across all wallet addresses in this tx.
   * Positive = net receive; negative = net send.
   */
  deltaSats: number;
  /**
   * False when the backend only supplied txid + height (WoC testnet
   * fallback). UI should hide +/- amounts for these rows.
   */
  deltaKnown?: boolean;
}

export interface HistorySnapshot {
  /** ISO 8601 timestamp the fetch completed. */
  at: string;
  entries: WalletTxEntry[];
  /** Total addresses queried. */
  addressesQueried: number;
  /**
   * True when the fetch hit {@link MAX_HISTORY_ENTRIES} and older txs may
   * exist on-chain beyond what we stored.
   */
  truncated?: boolean;
}

export interface FetchHistoryOptions {
  /**
   * Gap-walk stop index on the receive branch (next unprobed index).
   * Preferred source for the address range when present on lastScan.
   */
  stoppedAtReceive?: number;
  /** Gap-walk stop index on the change branch. */
  stoppedAtChange?: number;
  /**
   * Highest receive index seen with a UTXO (from lastScan).
   * Legacy fallback when `stoppedAtReceive` is absent.
   */
  lastReceiveUsed?: number;
  /**
   * Highest change index seen with a UTXO (from lastScan).
   * Legacy fallback when `stoppedAtChange` is absent.
   */
  lastChangeUsed?: number;
  /**
   * Extra addresses to probe beyond the gap-walk stop on each branch.
   * Default 5 — catches cases where the scan slightly undershot.
   */
  lookahead?: number;
  /** Wallet network; selects address encoding. Defaults to "main". */
  network?: NetworkT;
  /**
   * Max entries to fetch and store (newest first).
   * Defaults to {@link MAX_HISTORY_ENTRIES}.
   */
  limit?: number;
  /** Progress callback — phase distinguishes address scan vs tx detail fetch. */
  onProgress?: (
    done: number,
    total: number,
    phase: "addresses" | "transactions",
  ) => void;
  /**
   * Required when `network === "test"`. Bitails' testnet API
   * (`test-api.bitails.io`) is frequently unavailable; WoC supplies
   * tx history instead (txid + height only — no sat deltas).
   */
  woc?: WocClient;
}

/**
 * Exclusive upper bound for address indices on one branch (query 0 … end-1).
 *
 * When `stoppedAt` is present it is the next unprobed index after the gap
 * walk; we add `lookahead` on top. Legacy snapshots without `stoppedAt`
 * fall back to at least `DEFAULT_GAP_LIMIT + lookahead` addresses.
 */
export function historyBranchEnd(
  stoppedAt: number | undefined,
  lastUsed: number | undefined,
  lookahead: number,
): number {
  if (stoppedAt != null && stoppedAt > 0) {
    return stoppedAt + lookahead;
  }
  const fromLastUsed = Math.max(lastUsed ?? -1, -1) + 1 + lookahead;
  const fromGap = DEFAULT_GAP_LIMIT + lookahead;
  return Math.max(fromLastUsed, fromGap);
}

function chunkArray<T>(arr: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let i = 0; i < arr.length; i += size) {
    chunks.push(arr.slice(i, i + size));
  }
  return chunks;
}

/** Bitails page size when walking `from` offsets per address batch. */
const BITAILS_HISTORY_FETCH_PAGE = 100;

function buildHistoryAddresses(
  accountXpub: string,
  opts: FetchHistoryOptions,
): { addresses: string[]; network: NetworkT } {
  const lookahead = opts.lookahead ?? 5;
  const network: NetworkT = opts.network ?? "main";
  const recvEnd = historyBranchEnd(
    opts.stoppedAtReceive,
    opts.lastReceiveUsed,
    lookahead,
  );
  const chgEnd = historyBranchEnd(
    opts.stoppedAtChange,
    opts.lastChangeUsed,
    lookahead,
  );
  const addresses: string[] = [];
  for (let i = 0; i < recvEnd; i++) {
    addresses.push(deriveAddress(accountXpub, RECEIVE_BRANCH, i, network).address);
  }
  for (let i = 0; i < chgEnd; i++) {
    addresses.push(deriveAddress(accountXpub, CHANGE_BRANCH, i, network).address);
  }
  return { addresses, network };
}

async function fetchAllHistoryForChunk(
  bitails: BitailsClient,
  addresses: string[],
): Promise<BitailsHistoryEntry[]> {
  const all: BitailsHistoryEntry[] = [];
  let from = 0;
  while (true) {
    const batch = await bitails.getHistoryBatch(addresses, {
      limit: BITAILS_HISTORY_FETCH_PAGE,
      from,
    });
    all.push(...batch);
    if (batch.length < BITAILS_HISTORY_FETCH_PAGE) break;
    from += batch.length;
  }
  return all;
}

function aggregateByTxid(entries: BitailsHistoryEntry[]): WalletTxEntry[] {
  const byTxid = new Map<string, WalletTxEntry>();
  for (const h of entries) {
    if (!h.txid) continue;
    const existing = byTxid.get(h.txid);
    if (existing) {
      existing.deltaSats += h.deltaSats;
      if (h.blockHeight > existing.blockHeight) {
        existing.blockHeight = h.blockHeight;
        existing.timestamp = h.timestamp;
      }
    } else {
      byTxid.set(h.txid, {
        txid: h.txid,
        timestamp: h.timestamp,
        blockHeight: h.blockHeight,
        deltaSats: h.deltaSats,
      });
    }
  }
  return Array.from(byTxid.values()).sort((a, b) => {
    if (a.blockHeight === 0 && b.blockHeight !== 0) return -1;
    if (b.blockHeight === 0 && a.blockHeight !== 0) return 1;
    return b.blockHeight - a.blockHeight;
  });
}

/**
 * Fetch and merge transaction history for an account xpub.
 * Returns a {@link HistorySnapshot} ready to persist on the wallet record.
 */
export async function fetchWalletHistory(
  accountXpub: string,
  bitails: BitailsClient,
  opts: FetchHistoryOptions = {},
): Promise<HistorySnapshot> {
  const maxEntries = opts.limit ?? MAX_HISTORY_ENTRIES;
  const { addresses, network } = buildHistoryAddresses(accountXpub, opts);

  if (network === "test") {
    if (!opts.woc) {
      throw new Error("testnet history requires a WoC client (Bitails test API unavailable)");
    }
    return fetchWalletHistoryViaWoc(
      addresses,
      opts.woc,
      maxEntries,
      opts.onProgress,
    );
  }

  const allEntries: BitailsHistoryEntry[] = [];
  const chunks = chunkArray(addresses, BITAILS_BULK_BATCH_MAX);
  let done = 0;
  for (const chunk of chunks) {
    const batchEntries = await fetchAllHistoryForChunk(bitails, chunk);
    allEntries.push(...batchEntries);
    done += chunk.length;
    opts.onProgress?.(done, addresses.length, "addresses");
  }

  const sorted = aggregateByTxid(allEntries);
  const truncated = sorted.length > maxEntries;

  return {
    at: new Date().toISOString(),
    entries: sorted.slice(0, maxEntries),
    addressesQueried: addresses.length,
    ...(truncated ? { truncated: true } : {}),
  };
}

async function fetchWalletHistoryViaWoc(
  addresses: string[],
  woc: WocClient,
  maxEntries: number,
  onProgress?: (
    done: number,
    total: number,
    phase: "addresses" | "transactions",
  ) => void,
): Promise<HistorySnapshot> {
  const walletSet = new Set(addresses);
  const byTxid = new Map<string, WalletTxEntry>();
  const chunks = chunkArray(addresses, BITAILS_BULK_BATCH_MAX);
  let done = 0;
  for (const chunk of chunks) {
    const rows = await woc.getAddressHistoryBatch(chunk);
    for (const row of rows) {
      for (const h of row.entries) {
        const existing = byTxid.get(h.txid);
        if (!existing || h.blockHeight > existing.blockHeight) {
          byTxid.set(h.txid, {
            txid: h.txid,
            timestamp: 0,
            blockHeight: h.blockHeight,
            deltaSats: 0,
            deltaKnown: false,
          });
        }
      }
    }
    done += chunk.length;
    onProgress?.(done, addresses.length, "addresses");
  }
  const sorted = Array.from(byTxid.values()).sort((a, b) => {
    if (a.blockHeight === 0 && b.blockHeight !== 0) return -1;
    if (b.blockHeight === 0 && a.blockHeight !== 0) return 1;
    return b.blockHeight - a.blockHeight;
  });
  const truncated = sorted.length > maxEntries;
  const stored = sorted.slice(0, maxEntries);
  const enrichCount = Math.min(HISTORY_PAGE_SIZE, stored.length);
  const txCache = new Map<string, WocTxDetail>();
  for (let i = 0; i < enrichCount; i++) {
    const entry = stored[i]!;
    try {
      stored[i] = await enrichWalletTxFromWoc(
        entry.txid,
        entry.blockHeight,
        walletSet,
        woc,
        txCache,
      );
    } catch {
      // Keep txid + height; amount stays unknown for this row.
    }
    onProgress?.(i + 1, enrichCount, "transactions");
  }
  return {
    at: new Date().toISOString(),
    entries: stored,
    addressesQueried: addresses.length,
    ...(truncated ? { truncated: true } : {}),
  };
}

/**
 * Fill in sat deltas for testnet history rows that only have txid + height.
 * Mutates and returns `entries` (same array reference).
 */
export async function enrichWalletHistorySlice(
  entries: WalletTxEntry[],
  walletAddresses: string[],
  woc: WocClient,
  startIndex: number,
  endIndex: number,
  onProgress?: (done: number, total: number) => void,
): Promise<WalletTxEntry[]> {
  const walletSet = new Set(walletAddresses);
  const txCache = new Map<string, WocTxDetail>();
  const end = Math.min(endIndex, entries.length);
  let enriched = 0;
  for (let i = startIndex; i < end; i++) {
    const entry = entries[i]!;
    if (entry.deltaKnown !== false) {
      enriched += 1;
      onProgress?.(enriched, end - startIndex);
      continue;
    }
    try {
      entries[i] = await enrichWalletTxFromWoc(
        entry.txid,
        entry.blockHeight,
        walletSet,
        woc,
        txCache,
      );
    } catch {
      // Keep txid + height; amount stays unknown for this row.
    }
    enriched += 1;
    onProgress?.(enriched, end - startIndex);
  }
  return entries;
}

/** Derive the same address list used for a history fetch (for WoC enrichment). */
export function historyAddressesForWallet(
  accountXpub: string,
  opts: FetchHistoryOptions,
): string[] {
  return buildHistoryAddresses(accountXpub, opts).addresses;
}

function bsvToSats(valueBsv: number): number {
  return Math.round(valueBsv * 100_000_000);
}

async function loadWocTx(
  txid: string,
  woc: WocClient,
  cache: Map<string, WocTxDetail>,
): Promise<WocTxDetail> {
  const cached = cache.get(txid);
  if (cached) return cached;
  const tx = await woc.getTxDetail(txid);
  cache.set(txid, tx);
  return tx;
}

/**
 * Compute net wallet delta for one tx by fetching vout credits and
 * matching vin prevouts (cached per history fetch).
 */
export async function enrichWalletTxFromWoc(
  txid: string,
  fallbackHeight: number,
  walletSet: Set<string>,
  woc: WocClient,
  cache: Map<string, WocTxDetail>,
): Promise<WalletTxEntry> {
  const tx = await loadWocTx(txid, woc, cache);
  let deltaSats = 0;
  for (const out of tx.vout) {
    if (out.address && walletSet.has(out.address)) {
      deltaSats += bsvToSats(out.valueBsv);
    }
  }
  for (const inn of tx.vin) {
    if (inn.coinbase) continue;
    if (!inn.txid) continue;
    const prev = await loadWocTx(inn.txid, woc, cache);
    const prevOut = prev.vout[inn.vout];
    if (prevOut?.address && walletSet.has(prevOut.address)) {
      deltaSats -= bsvToSats(prevOut.valueBsv);
    }
  }
  return {
    txid,
    timestamp: tx.time,
    blockHeight: tx.blockHeight || fallbackHeight,
    deltaSats,
    deltaKnown: true,
  };
}

/**
 * Format a unix timestamp (seconds) as a short human-readable string.
 * Returns "pending" for unconfirmed (timestamp 0).
 */
export function formatTxTimestamp(ts: number): string {
  if (ts === 0) return "pending";
  const d = new Date(ts * 1000);
  const now = Date.now();
  const diffMs = now - d.getTime();
  if (diffMs < 0) return d.toLocaleDateString();
  const diffSec = diffMs / 1000;
  if (diffSec < 60) return "just now";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  if (diffSec < 7 * 86400) return `${Math.floor(diffSec / 86400)}d ago`;
  return d.toLocaleDateString();
}

/**
 * Re-export for consumers that hold a raw `BitailsHistoryEntry[]` from
 * the client (e.g. tests) and want the same merge logic without a full
 * xpub scan.
 */
export function mergeHistoryEntries(
  entries: BitailsHistoryEntry[],
): WalletTxEntry[] {
  const byTxid = new Map<string, WalletTxEntry>();
  for (const h of entries) {
    if (!h.txid) continue;
    const existing = byTxid.get(h.txid);
    if (existing) {
      existing.deltaSats += h.deltaSats;
    } else {
      byTxid.set(h.txid, { ...h });
    }
  }
  return Array.from(byTxid.values()).sort((a, b) => b.blockHeight - a.blockHeight);
}

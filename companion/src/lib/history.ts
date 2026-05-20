/**
 * Wallet transaction history fetcher.
 *
 * Uses the Bitails `POST /address/history/multi` endpoint, which returns
 * the net satoshi delta per tx per address — so we can tell a receive
 * (+sats) from a send (-sats) without fetching the full raw tx.
 *
 * Strategy:
 *   1. Derive all used receive + change addresses (up to the last-used
 *      indices stored in the most recent UTXO scan snapshot, plus a small
 *      look-ahead).
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
import { HISTORY_PAGE_SIZE } from "./config.js";

export interface WalletTxEntry {
  txid: string;
  /** Unix timestamp (seconds). 0 = unconfirmed. */
  timestamp: number;
  /** Block height (0 = unconfirmed). */
  blockHeight: number;
  /**
   * Net satoshi change across all wallet addresses in this tx.
   * Positive = net receive; negative = net send.
   */
  deltaSats: number;
}

export interface HistorySnapshot {
  /** ISO 8601 timestamp the fetch completed. */
  at: string;
  entries: WalletTxEntry[];
  /** Total addresses queried. */
  addressesQueried: number;
}

export interface FetchHistoryOptions {
  /**
   * Highest receive index seen with a UTXO (from lastScan).
   * We query 0 … max(lastReceiveUsed, 0) + lookahead.
   */
  lastReceiveUsed?: number;
  /**
   * Highest change index seen with a UTXO (from lastScan).
   * We query 0 … max(lastChangeUsed, 0) + lookahead.
   */
  lastChangeUsed?: number;
  /**
   * Extra addresses to probe beyond lastUsed on each branch.
   * Default 5 — catches cases where the scan slightly undershot.
   */
  lookahead?: number;
  /** Wallet network; selects address encoding. Defaults to "main". */
  network?: NetworkT;
  /** Max entries to return (newest first). Defaults to HISTORY_PAGE_SIZE. */
  limit?: number;
  /** Progress callback. */
  onProgress?: (done: number, total: number) => void;
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
  const lookahead = opts.lookahead ?? 5;
  const network: NetworkT = opts.network ?? "main";
  const limit = opts.limit ?? HISTORY_PAGE_SIZE;

  // Build address list for both branches.
  const addresses: string[] = [];
  const recvEnd = Math.max(opts.lastReceiveUsed ?? -1, -1) + 1 + lookahead;
  const chgEnd = Math.max(opts.lastChangeUsed ?? -1, -1) + 1 + lookahead;

  for (let i = 0; i < recvEnd; i++) {
    addresses.push(deriveAddress(accountXpub, RECEIVE_BRANCH, i, network).address);
  }
  for (let i = 0; i < chgEnd; i++) {
    addresses.push(deriveAddress(accountXpub, CHANGE_BRANCH, i, network).address);
  }

  // Fetch in batches.
  const byTxid = new Map<string, WalletTxEntry>();
  let done = 0;

  for (let i = 0; i < addresses.length; i += BITAILS_BULK_BATCH_MAX) {
    const batch = addresses.slice(i, i + BITAILS_BULK_BATCH_MAX);
    const results = await bitails.getHistoryBatch(batch);
    for (const r of results) {
      for (const h of r.entries) {
        if (!h.txid) continue;
        const existing = byTxid.get(h.txid);
        if (existing) {
          existing.deltaSats += h.deltaSats;
          // Keep the most recent block info if one is unconfirmed.
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
    }
    done += batch.length;
    opts.onProgress?.(done, addresses.length);
  }

  // Sort: unconfirmed first (height 0), then descending by height.
  const sorted = Array.from(byTxid.values()).sort((a, b) => {
    if (a.blockHeight === 0 && b.blockHeight !== 0) return -1;
    if (b.blockHeight === 0 && a.blockHeight !== 0) return 1;
    return b.blockHeight - a.blockHeight;
  });

  return {
    at: new Date().toISOString(),
    entries: sorted.slice(0, limit),
    addressesQueried: addresses.length,
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

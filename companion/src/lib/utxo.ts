/**
 * Gap-limit UTXO scanner for a paired wallet's account xpub.
 *
 * Walks `m/0/<i>` (receive) and `m/1/<i>` (change) branches starting at
 * index 0. For each address, asks the configured backend for unspent
 * outputs. Stops a branch after `GAP_LIMIT` consecutive *unused* addresses
 * (no UTXOs AND no recorded history). BIP44 standard gap is 20.
 *
 * For v1 we treat "no UTXOs returned" as a proxy for "unused" — strictly
 * speaking a fully-spent address still counts as used, so a future
 * iteration can swap in the WoC `/address/{a}/history` endpoint when that
 * matters. For brand-new HD wallets the cheaper check is correct.
 *
 * Output: a flat list of `WalletUtxo` entries each tagged with the BIP32
 * derivation `[change, index]` so the Pi can re-derive the signing key.
 * Sorted by descending value (greedy-friendly).
 *
 * Backend calls
 * -------------
 * The scanner uses WoC's bulk endpoint via
 * {@link WocClient.getUnspentBatch} — up to
 * {@link WOC_BULK_BATCH_MAX} addresses per HTTP request. A typical
 * empty-wallet scan therefore costs **2 API calls** (one bulk per
 * branch), not 40 individual GETs, which sails comfortably under
 * WoC's ~3 req/s unauthenticated rate limit.
 */
import {
  CHANGE_BRANCH,
  RECEIVE_BRANCH,
  deriveAddress,
} from "./derive.js";
import type { NetworkT } from "./envelope.js";
import {
  WOC_BULK_BATCH_MAX,
  type WocBulkUnspentResult,
  type WocClient,
} from "./woc.js";

export const DEFAULT_GAP_LIMIT = 20;
/** Default addresses derived per bulk WoC call. Capped at the WoC bulk max. */
export const DEFAULT_BATCH = WOC_BULK_BATCH_MAX;

export interface WalletUtxo {
  txid: string;
  vout: number;
  sats: number;
  /** Confirmation block height (0 = mempool). */
  height: number;
  /** Address that owns this output. */
  address: string;
  /** BIP32 sub-path leg from the account xpub: `[change, index]`. */
  derivation: [number, number];
}

export interface ScanResult {
  utxos: WalletUtxo[];
  totalSats: number;
  /** Highest receive index seen with a UTXO (`-1` if none). */
  lastReceiveUsed: number;
  /** Highest change index seen with a UTXO (`-1` if none). */
  lastChangeUsed: number;
  /** Number of addresses probed across both branches. */
  addressesScanned: number;
  /** Per-branch first-gap index (= where the scan stopped). */
  stoppedAt: { receive: number; change: number };
}

export interface ScanOptions {
  gapLimit?: number;
  /**
   * How many addresses to bundle into a single bulk WoC call. Capped
   * at {@link WOC_BULK_BATCH_MAX}; values higher than that are
   * silently clamped so callers can pass a "natural" gap-sized
   * batch without worrying about the WoC limit.
   */
  batch?: number;
  /** Skip addresses below this index (resume hint). */
  startReceive?: number;
  startChange?: number;
  /**
   * Wallet's network — selects the base58check P2PKH prefix the
   * scanner asks WoC about. Defaults to `"main"` for backwards
   * compatibility with callers that haven't been updated to pass it
   * explicitly. The matching `WocClient` base URL must be picked by
   * the caller; this option only affects address rendering.
   */
  network?: NetworkT;
  /** Progress callback (called once per address probed). */
  onProgress?: (info: {
    branch: number;
    index: number;
    address: string;
    found: number;
  }) => void;
  /**
   * Async fetch hook for one bulk window — defaults to
   * {@link WocClient.getUnspentBatch}. Tests stub this with an
   * in-memory address→UTXOs map.
   */
  fetchUnspentBatch?: (
    addresses: string[],
  ) => Promise<WocBulkUnspentResult[]>;
}

export async function scanWalletUtxos(
  accountXpub: string,
  woc: WocClient,
  opts: ScanOptions = {},
): Promise<ScanResult> {
  const gap = opts.gapLimit ?? DEFAULT_GAP_LIMIT;
  const rawBatch = opts.batch ?? DEFAULT_BATCH;
  const batch = Math.min(rawBatch, WOC_BULK_BATCH_MAX);
  const network: NetworkT = opts.network ?? "main";
  const fetchBatch =
    opts.fetchUnspentBatch ?? ((addrs: string[]) => woc.getUnspentBatch(addrs));

  const utxos: WalletUtxo[] = [];
  let total = 0;
  let lastRecvUsed = -1;
  let lastChangeUsed = -1;
  let addressesScanned = 0;
  const stoppedAt = { receive: 0, change: 0 };

  for (const branch of [RECEIVE_BRANCH, CHANGE_BRANCH]) {
    let index =
      branch === RECEIVE_BRANCH
        ? (opts.startReceive ?? 0)
        : (opts.startChange ?? 0);
    let consecutiveEmpty = 0;
    while (consecutiveEmpty < gap) {
      // Window size shrinks as we approach the gap limit so we don't
      // burn a full WoC bulk call probing addresses we're going to
      // discard once `consecutiveEmpty === gap`.
      const remainingBeforeGap = gap - consecutiveEmpty;
      const windowSize = Math.min(batch, remainingBeforeGap);
      const probes: { index: number; address: string }[] = [];
      for (let i = 0; i < windowSize; i++) {
        const idx = index + i;
        const d = deriveAddress(accountXpub, branch, idx, network);
        probes.push({ index: idx, address: d.address });
      }
      const results = await fetchBatch(probes.map((p) => p.address));
      // Map results back by address. WoC returns them in input order
      // but we don't rely on that; an address-keyed map is robust to
      // future server changes.
      const byAddress = new Map<string, WocBulkUnspentResult>();
      for (const r of results) byAddress.set(r.address, r);
      for (const p of probes) {
        const found = byAddress.get(p.address)?.utxos ?? [];
        addressesScanned += 1;
        opts.onProgress?.({
          branch,
          index: p.index,
          address: p.address,
          found: found.length,
        });
        if (found.length === 0) {
          consecutiveEmpty += 1;
          if (consecutiveEmpty >= gap) break;
        } else {
          consecutiveEmpty = 0;
          if (branch === RECEIVE_BRANCH) lastRecvUsed = p.index;
          else lastChangeUsed = p.index;
          for (const u of found) {
            utxos.push({
              txid: u.txid,
              vout: u.vout,
              sats: u.sats,
              height: u.height,
              address: p.address,
              derivation: [branch, p.index],
            });
            total += u.sats;
          }
        }
      }
      index += windowSize;
    }
    if (branch === RECEIVE_BRANCH) stoppedAt.receive = index;
    else stoppedAt.change = index;
  }

  utxos.sort((a, b) => b.sats - a.sats);
  return {
    utxos,
    totalSats: total,
    lastReceiveUsed: lastRecvUsed,
    lastChangeUsed: lastChangeUsed,
    addressesScanned,
    stoppedAt,
  };
}

/**
 * Lightweight receive-index scan.
 *
 * Starting from `fromIndex`, derives up to `lookAhead` receive addresses and
 * finds the first one with zero UTXOs (confirmed + mempool). Returns the index
 * of that address — i.e. the next safely unused receive address.
 *
 * Uses a single `getUnspentBatch` call so it's fast and cheap.
 */
export async function scanNextReceiveIndex(
  accountXpub: string,
  woc: WocClient,
  fromIndex: number,
  network: NetworkT,
  lookAhead = DEFAULT_GAP_LIMIT,
): Promise<number> {
  const probes: { index: number; address: string }[] = [];
  for (let i = 0; i < lookAhead; i++) {
    const idx = fromIndex + i;
    const d = deriveAddress(accountXpub, RECEIVE_BRANCH, idx, network);
    probes.push({ index: idx, address: d.address });
  }

  const results = await woc.getUnspentBatch(probes.map((p) => p.address));
  const usedSet = new Set(
    results.filter((r) => r.utxos.length > 0).map((r) => r.address),
  );

  for (const p of probes) {
    if (!usedSet.has(p.address)) return p.index;
  }
  // All look-ahead addresses used — return next beyond the window
  return fromIndex + lookAhead;
}

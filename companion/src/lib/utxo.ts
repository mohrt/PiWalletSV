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
 */
import {
  CHANGE_BRANCH,
  RECEIVE_BRANCH,
  deriveAddress,
} from "./derive.js";
import type { NetworkT } from "./envelope.js";
import type { WocClient, WocUnspentEntry } from "./woc.js";

export const DEFAULT_GAP_LIMIT = 20;
export const DEFAULT_BATCH = 5;

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
  /** How many addresses to derive at a time (one fetch per address). */
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
  /** Async fetch hook — defaults to woc.getUnspent. Useful for tests. */
  fetchUnspent?: (address: string) => Promise<WocUnspentEntry[]>;
}

export async function scanWalletUtxos(
  accountXpub: string,
  woc: WocClient,
  opts: ScanOptions = {},
): Promise<ScanResult> {
  const gap = opts.gapLimit ?? DEFAULT_GAP_LIMIT;
  const batch = opts.batch ?? DEFAULT_BATCH;
  const network: NetworkT = opts.network ?? "main";
  const fetchUnspent =
    opts.fetchUnspent ?? ((addr: string) => woc.getUnspent(addr));

  const utxos: WalletUtxo[] = [];
  let total = 0;
  let lastRecvUsed = -1;
  let lastChangeUsed = -1;
  let addressesScanned = 0;
  const stoppedAt = { receive: 0, change: 0 };

  for (const branch of [RECEIVE_BRANCH, CHANGE_BRANCH]) {
    let index = branch === RECEIVE_BRANCH
      ? opts.startReceive ?? 0
      : opts.startChange ?? 0;
    let consecutiveEmpty = 0;
    while (consecutiveEmpty < gap) {
      const probeStart = index;
      const probeEnd = Math.min(index + batch, index + (gap - consecutiveEmpty));
      const probes: { index: number; address: string }[] = [];
      for (let i = probeStart; i < probeEnd; i++) {
        const d = deriveAddress(accountXpub, branch, i, network);
        probes.push({ index: i, address: d.address });
      }
      const results = await Promise.all(
        probes.map((p) => fetchUnspent(p.address)),
      );
      for (let j = 0; j < probes.length; j++) {
        const p = probes[j];
        const found = results[j];
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
      index = probeEnd;
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

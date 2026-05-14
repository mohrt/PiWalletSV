/**
 * Split a wallet's UTXO set into confirmed vs. pending (mempool) totals.
 *
 * Mirrors the convention used elsewhere in the companion: an entry
 * with `height === 0` is in WoC's mempool but not yet mined, anything
 * with `height > 0` is on-chain at that block height. The split is
 * surfaced in the wallet-detail card so an operator who just received
 * (or just sent) sats can tell at a glance whether the figure they're
 * looking at is fully confirmed or includes in-flight value that
 * could in principle still be evicted from the mempool before
 * confirmation.
 */
export interface BalanceSplit {
  /** Sum of `height > 0` UTXOs. */
  confirmedSats: number;
  /** Sum of `height === 0` UTXOs. */
  pendingSats: number;
  /** Whether any UTXO is unconfirmed. */
  hasPending: boolean;
  /** Whether *all* UTXOs are unconfirmed (and there's at least one). */
  allPending: boolean;
}

export interface UtxoLike {
  sats: number;
  height: number;
}

export function splitConfirmedPending(utxos: readonly UtxoLike[]): BalanceSplit {
  let confirmedSats = 0;
  let pendingSats = 0;
  let confirmedCount = 0;
  let pendingCount = 0;
  for (const u of utxos) {
    if (u.height > 0) {
      confirmedSats += u.sats;
      confirmedCount += 1;
    } else {
      // height 0 (mempool) — also catches negative or NaN as a safety
      // net; treating "unknown height" as pending is the conservative
      // call (we'd rather over-warn than mislead).
      pendingSats += u.sats;
      pendingCount += 1;
    }
  }
  return {
    confirmedSats,
    pendingSats,
    hasPending: pendingCount > 0,
    allPending: pendingCount > 0 && confirmedCount === 0,
  };
}

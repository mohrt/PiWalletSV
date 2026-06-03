/**
 * Greedy UTXO coin selection + P2PKH fee estimation.
 *
 * Strategy
 * --------
 * "Largest first" is the simplest selection rule that produces small,
 * deterministic transactions. We pick UTXOs sorted by descending sats
 * until we cover `target + fee + dust`, i.e. until the remainder after
 * fees is at least the dust threshold. The remainder always becomes a
 * dedicated change output.
 *
 * v1 protocol requires an explicit change output — see
 * docs/protocol/spv.md §1.6. If no combination of available UTXOs leaves
 * above-dust change, selection fails with `CoinSelectError`; the caller
 * should ask the user to either lower the target amount or wait for more
 * UTXOs to consolidate.
 *
 * Fee model
 * ---------
 * Per-input cost is fixed for our v1 wallet because every input is a
 * P2PKH spend (148 bytes including signature). Likewise every output
 * is P2PKH (34 bytes). Transaction overhead is ~10 bytes (version +
 * locktime + input/output VarInts). Total bytes ~=
 *
 *     OVERHEAD + nInputs * P2PKH_INPUT + nOutputs * P2PKH_OUTPUT
 *
 * Fee = ceil(bytes * feeRateSatsPerKb / 1000). v1 always has 2 outputs
 * (recipient + change), so nOutputs is fixed at 2 in the fee formula.
 */

export const P2PKH_INPUT_BYTES = 148;
export const P2PKH_OUTPUT_BYTES = 34;
export const TX_OVERHEAD_BYTES = 10;
/** Minimum sats a change output must carry; selections that can't reach
 *  this threshold are rejected. */
export const DUST_THRESHOLD_SATS = 546;

export class CoinSelectError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CoinSelectError";
  }
}

export interface SelectableUtxo {
  txid: string;
  vout: number;
  sats: number;
  derivation: [number, number];
}

export interface SelectionResult<T extends SelectableUtxo> {
  inputs: T[];
  totalInputSats: number;
  /** Change sats (always at least `dustSats`). */
  changeSats: number;
  /** Estimated bytes for the assembled 2-output tx. */
  estimatedBytes: number;
  /** Estimated miner fee. */
  feeSats: number;
}

/**
 * Estimate the on-wire size of a P2PKH transaction with the given counts.
 */
export function estimateTxBytes(nInputs: number, nOutputs: number): number {
  return TX_OVERHEAD_BYTES + nInputs * P2PKH_INPUT_BYTES + nOutputs * P2PKH_OUTPUT_BYTES;
}

/**
 * Estimate miner fee for a P2PKH tx with `nInputs` and `nOutputs`, at
 * `feeRateSatsPerKb` (sats per 1000 bytes — standard BSV units).
 */
export function estimateFee(
  nInputs: number,
  nOutputs: number,
  feeRateSatsPerKb: number,
): number {
  const bytes = estimateTxBytes(nInputs, nOutputs);
  return Math.ceil((bytes * feeRateSatsPerKb) / 1000);
}

/**
 * Greedy "largest-first" selection that always produces an above-dust
 * change output. Throws `CoinSelectError` if no subset of `utxos` covers
 * `targetSats + fee + dust`.
 *
 * @param utxos        Available UTXOs (any order; selector sorts internally).
 * @param targetSats   Amount to pay to the recipient (excluding fee).
 * @param feeRateSatskb Fee rate in sats per 1000 bytes (default 500).
 * @param dustSats     Minimum change sats; selections below this fail.
 */
export function selectUtxosGreedy<T extends SelectableUtxo>(
  utxos: T[],
  targetSats: number,
  feeRateSatskb: number = 500,
  dustSats: number = DUST_THRESHOLD_SATS,
): SelectionResult<T> {
  if (!Number.isInteger(targetSats) || targetSats <= 0) {
    throw new CoinSelectError(`targetSats must be a positive integer, got ${targetSats}`);
  }
  if (!Number.isInteger(feeRateSatskb) || feeRateSatskb < 0) {
    throw new CoinSelectError(`feeRateSatskb must be a non-negative integer, got ${feeRateSatskb}`);
  }
  if (utxos.length === 0) {
    throw new CoinSelectError("no UTXOs available");
  }

  // Sort by descending sats. (Stable-ish via index tiebreaker.)
  const sorted = [...utxos].sort((a, b) => b.sats - a.sats);

  const chosen: T[] = [];
  let total = 0;
  for (const u of sorted) {
    chosen.push(u);
    total += u.sats;
    const fee = estimateFee(chosen.length, 2, feeRateSatskb);
    const change = total - targetSats - fee;
    if (change >= dustSats) {
      return {
        inputs: chosen,
        totalInputSats: total,
        changeSats: change,
        estimatedBytes: estimateTxBytes(chosen.length, 2),
        feeSats: fee,
      };
    }
  }

  // We consumed every UTXO and still couldn't produce above-dust change.
  // Surface a user-actionable message: either lower the target or wait
  // for more UTXOs to consolidate.
  const finalFee = estimateFee(chosen.length, 2, feeRateSatskb);
  const need = targetSats + finalFee + dustSats;
  throw new CoinSelectError(
    `insufficient funds: have ${total} sats across ${chosen.length} UTXO(s); ` +
      `need at least ${need} sats to leave above-dust change ` +
      `(target ${targetSats} + fee ${finalFee} + dust ${dustSats})`,
  );
}

/**
 * Largest recipient amount that still leaves above-dust change at `feeRateSatskb`.
 * Uses binary search over `selectUtxosGreedy` so the result matches real selection.
 */
export function computeMaxSendSats(
  utxos: readonly SelectableUtxo[],
  feeRateSatskb: number,
  dustSats: number = DUST_THRESHOLD_SATS,
): number {
  if (utxos.length === 0) return 0;
  const totalIn = utxos.reduce((a, u) => a + u.sats, 0);
  let lo = 0;
  let hi = totalIn;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    try {
      selectUtxosGreedy([...utxos], mid, feeRateSatskb, dustSats);
      lo = mid;
    } catch {
      hi = mid - 1;
    }
  }
  return lo;
}

/**
 * Greedy UTXO coin selection + P2PKH fee estimation.
 *
 * Strategy
 * --------
 * "Largest first" is the simplest selection rule that produces small,
 * deterministic transactions. We pick UTXOs sorted by descending sats
 * until we cover `target + estimatedFee`. If the remainder after fee is
 * ≤ `DUST_THRESHOLD` it gets folded into the fee (no change output),
 * otherwise it becomes a change output.
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
 * Fee = ceil(bytes * feeRateSatsPerKb / 1000).
 */

export const P2PKH_INPUT_BYTES = 148;
export const P2PKH_OUTPUT_BYTES = 34;
export const TX_OVERHEAD_BYTES = 10;
/** A change output below this many sats is wasteful; fold into fee. */
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

export interface SelectionInput<T extends SelectableUtxo> {
  utxo: T;
}

export interface SelectionResult<T extends SelectableUtxo> {
  inputs: T[];
  totalInputSats: number;
  /** True if the dust check absorbed the change into the fee. */
  hasChange: boolean;
  /** Change sats (0 when `hasChange` is false). */
  changeSats: number;
  /** Estimated bytes for the assembled tx (with or without change). */
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
 * Greedy "largest-first" selection.
 *
 * @param utxos        Available UTXOs (any order; selector sorts internally).
 * @param targetSats   Amount to pay to the recipient (excluding fee).
 * @param feeRateSatskb Fee rate in sats per 1000 bytes (default 500).
 * @param dustSats     Minimum change before we fold it into fee.
 * @throws CoinSelectError if no combination of UTXOs covers target + fee.
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
    // After adding this UTXO, decide whether we'd have change.
    const withChangeFee = estimateFee(chosen.length, 2, feeRateSatskb);
    const noChangeFee = estimateFee(chosen.length, 1, feeRateSatskb);

    // Branch 1: with change output — need total >= target + change + fee.
    if (total >= targetSats + dustSats + withChangeFee) {
      const change = total - targetSats - withChangeFee;
      return {
        inputs: chosen,
        totalInputSats: total,
        hasChange: true,
        changeSats: change,
        estimatedBytes: estimateTxBytes(chosen.length, 2),
        feeSats: withChangeFee,
      };
    }
    // Branch 2: drop the change output entirely; remainder goes to miner.
    if (total >= targetSats + noChangeFee) {
      return {
        inputs: chosen,
        totalInputSats: total,
        hasChange: false,
        changeSats: 0,
        estimatedBytes: estimateTxBytes(chosen.length, 1),
        feeSats: total - targetSats, // everything above target becomes fee
      };
    }
  }

  throw new CoinSelectError(
    `insufficient funds: have ${total} sats across ${chosen.length} UTXO(s), ` +
      `need at least ${targetSats + estimateFee(chosen.length, 2, feeRateSatskb)} sats`,
  );
}

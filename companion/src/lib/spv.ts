/**
 * Receive-side BRC-67 SPV verification for a wallet's UTXO snapshot.
 *
 * The companion's gap-limit scanner returns a flat list of UTXOs from
 * WhatsOnChain. Counting any of those toward "confirmed balance" is
 * only sound if we can prove each UTXO's funding tx really did land in
 * a block on the active chain at the reported height. Without that
 * proof, a malicious or compromised WoC mirror could inflate the
 * displayed balance by claiming a fictitious confirmation.
 *
 * This module closes that gap by:
 *
 * 1. Building a PoW-validated header chain from the firmware
 *    checkpoint up to the deepest confirmed UTXO via
 *    {@link "./headers.js".ensureChain}. The chain validation walk
 *    already proves each header self-links and clears its declared
 *    PoW target.
 * 2. For each confirmed UTXO, fetching the TSC Merkle proof from
 *    WoC, recomputing the implied Merkle root, and asserting it
 *    equals the validated-chain's root at the UTXO's block height.
 *    A mismatch means either WoC is lying about confirmation or the
 *    proof itself is malformed; either way, the UTXO does not count
 *    toward the trusted balance.
 *
 * Pending UTXOs (mempool, ``height === 0``) are passed through with
 * ``spvVerified: false`` and no proof requirement — there is no block
 * yet to anchor them against, and the wallet UI surfaces them under
 * a separate "pending" badge.
 */

import { tscProofToMerklePath } from "./proof-fetcher.js";
import {
  HeaderError,
  bytesEqual,
  ensureChain,
  type EnsuredChain,
} from "./headers.js";
import type { NetworkT } from "./envelope.js";
import { hexToBytes } from "./envelope.js";
import type { WalletUtxo } from "./utxo.js";
import type { WocClient } from "./woc.js";

export class SpvVerifyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SpvVerifyError";
  }
}

/**
 * One UTXO row enriched with the result of its SPV proof check.
 *
 * - ``spvVerified``: ``true`` only when the Merkle proof Recomputes
 *   to the validated-chain's root at ``height``.
 * - ``spvError``: short, single-line reason a verification failed —
 *   ``undefined`` for verified entries and for mempool entries (which
 *   are not subject to SPV).
 * - ``pending``: ``true`` for mempool entries; mirrors the convention
 *   used by {@link "./balance-split.js".splitConfirmedPending}.
 */
export interface VerifiedUtxo extends WalletUtxo {
  spvVerified: boolean;
  spvError?: string;
  pending: boolean;
}

export interface SpvVerificationSummary {
  utxos: VerifiedUtxo[];
  /** Number of confirmed UTXOs that passed PoW + Merkle verification. */
  verifiedCount: number;
  /** Number of confirmed UTXOs that failed (excluded from trusted balance). */
  failedCount: number;
  /** Number of mempool UTXOs (not subject to SPV). */
  pendingCount: number;
  /** Total sats across SPV-verified confirmed UTXOs. */
  verifiedSats: number;
  /** Total sats across confirmed UTXOs that failed verification. */
  failedSats: number;
  /** Total sats across pending mempool UTXOs. */
  pendingSats: number;
  /** The validated header chain used for the verification pass. */
  chain: EnsuredChain;
}

/**
 * Verify SPV proofs for every confirmed UTXO in ``utxos``.
 *
 * Builds the validated header chain once (covering all confirmed
 * heights) and reuses it across every per-UTXO check. Mempool entries
 * pass through untouched.
 *
 * Throws {@link SpvVerifyError} only for systemic failures (e.g.
 * `ensureChain` rejected the chain itself); per-UTXO failures are
 * surfaced via the returned `spvError` rather than propagated, so the
 * UI can still render the partial result.
 */
export async function verifyUtxoSpv(
  utxos: readonly WalletUtxo[],
  woc: WocClient,
  network: NetworkT,
): Promise<SpvVerificationSummary> {
  const confirmed = utxos.filter((u) => u.height > 0);
  const pending = utxos.filter((u) => u.height <= 0);
  const deepest = confirmed.reduce((max, u) => Math.max(max, u.height), 0);

  let chain: EnsuredChain;
  try {
    // Even an "all pending" wallet still produces a one-header chain
    // from the checkpoint so callers can surface the trust anchor's
    // height in the UI without a special case.
    const target = Math.max(deepest, 0);
    chain = await ensureChain(network, target, woc);
  } catch (e) {
    if (e instanceof HeaderError) {
      throw new SpvVerifyError(`header chain validation failed: ${e.message}`);
    }
    throw e;
  }

  const out: VerifiedUtxo[] = [];
  let verifiedCount = 0;
  let failedCount = 0;
  let pendingCount = 0;
  let verifiedSats = 0;
  let failedSats = 0;
  let pendingSats = 0;

  for (const u of pending) {
    pendingCount += 1;
    pendingSats += u.sats;
    out.push({ ...u, spvVerified: false, pending: true });
  }
  for (const u of confirmed) {
    const verdict = await verifyOne(u, chain, woc);
    if (verdict.spvVerified) {
      verifiedCount += 1;
      verifiedSats += u.sats;
    } else {
      failedCount += 1;
      failedSats += u.sats;
    }
    out.push({ ...u, ...verdict, pending: false });
  }

  return {
    utxos: out,
    verifiedCount,
    failedCount,
    pendingCount,
    verifiedSats,
    failedSats,
    pendingSats,
    chain,
  };
}

interface OneVerdict {
  spvVerified: boolean;
  spvError?: string;
}

async function verifyOne(
  u: WalletUtxo,
  chain: EnsuredChain,
  woc: WocClient,
): Promise<OneVerdict> {
  const expectedRoot = chain.merkleRootByHeight.get(u.height);
  if (!expectedRoot) {
    return {
      spvVerified: false,
      spvError: `validated chain has no entry at height ${u.height}`,
    };
  }
  let proof;
  try {
    proof = await woc.getTxProof(u.txid);
  } catch (e) {
    return { spvVerified: false, spvError: (e as Error).message };
  }
  if (!proof) {
    return {
      spvVerified: false,
      spvError: `WoC returned no proof for ${u.txid}`,
    };
  }
  let computedRootHex: string;
  try {
    const mp = tscProofToMerklePath(proof, u.txid, u.height);
    computedRootHex = mp.computeRoot(u.txid).toLowerCase();
  } catch (e) {
    return {
      spvVerified: false,
      spvError: `merkle path build failed: ${(e as Error).message}`,
    };
  }
  // The validated chain stores roots in raw byte order; the SDK
  // produces the displayed (big-endian) hex form. Compare on the raw
  // bytes to keep the byte-order convention explicit at one place.
  let computedRootBytes: Uint8Array;
  try {
    computedRootBytes = hexToBytes(computedRootHex).reverse();
  } catch (e) {
    return {
      spvVerified: false,
      spvError: `merkle root parse failed: ${(e as Error).message}`,
    };
  }
  if (!bytesEqual(computedRootBytes, expectedRoot)) {
    const expHex = Array.from(expectedRoot.slice().reverse())
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
    return {
      spvVerified: false,
      spvError:
        `proof root ${computedRootHex} != validated-chain root ` +
        `${expHex} at height ${u.height}`,
    };
  }
  return { spvVerified: true };
}

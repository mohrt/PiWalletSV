/**
 * Builds the per-input SPV payload an `unsigned_proposal` needs:
 *
 *   - `beef`        : binary BSV BEEF containing the funding tx with its
 *                     attached Merkle path. Pi-side bsv-sdk parses this
 *                     and finds the prior output by txid + vout.
 *   - `merklePath`  : raw binary Merkle path (matches Python
 *                     `MerklePath.to_binary()`).
 *   - `height`      : block height where the funding tx lives.
 *   - `merkleRoot`  : block's Merkle root (header anchor for SPV verify).
 *
 * The Merkle path comes from WhatsOnChain in TSC (BRC-10) shape:
 *   { blockHash, branches: [{ hash, pos: "L"|"R" }, ...], merkleRoot, txIndex }
 *
 * `txIndex` is the position of the funding tx within the block's tx
 * tree. WoC includes it sometimes; if absent we reconstruct it from
 * the `pos` flags (each "L" means the sibling is to our left, so our
 * own offset has bit-N set; "R" means bit-N is clear).
 *
 * Cross-check
 * -----------
 * BEEF produced here uses `@bsv/sdk`'s reference encoder. The Python
 * side uses `bsv-sdk` (different impl). Both are the official
 * implementations of the BRC-62 BEEF spec; we rely on spec compliance,
 * not impl coupling.
 */
import { MerklePath, Transaction } from "@bsv/sdk/transaction";

import type { WocClient, WocTxProof } from "./woc.js";

export interface InputProof {
  /** BSV BEEF blob for the input's funding tx (with Merkle path attached). */
  beef: Uint8Array;
  /** Atomic BEEF form persisted once for wallet-state sync/reuse. */
  atomicBeef?: Uint8Array;
  /** Standalone binary Merkle path (matches Python `MerklePath.to_binary()`). */
  merklePath: Uint8Array;
  /** Confirmation block height. */
  height: number;
  /** Block Merkle root hex string (big-endian, as WoC returns). */
  merkleRoot: string;
}

export class ProofFetchError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ProofFetchError";
  }
}

/**
 * Convert a WoC TSC-format proof into a `@bsv/sdk` MerklePath suitable
 * for attaching to a Transaction.
 *
 * TSC (BRC-10) gives us one sibling per Merkle tree level. With the leaf
 * `txIndex` known, the sibling's offset at level L is
 *
 *     siblingOffset = (txIndex >> L) ^ 1
 *
 * A `"*"` entry signals BSV's "duplicate-up" convention for unbalanced
 * trees: the missing sibling is recomputed by duplicating the node next
 * to it at the same level. `@bsv/sdk` represents this via `duplicate:
 * true`.
 */
export function tscProofToMerklePath(
  proof: WocTxProof,
  txid: string,
  blockHeight: number,
): MerklePath {
  if (proof.nodes.length === 0) {
    // Single-tx block (coinbase only). Use the SDK helper.
    return MerklePath.fromCoinbaseTxidAndHeight(txid, blockHeight);
  }

  const path: Array<Array<{
    offset: number;
    hash?: string;
    txid?: boolean;
    duplicate?: boolean;
  }>> = [];

  for (let level = 0; level < proof.nodes.length; level++) {
    const node = proof.nodes[level];
    const ourOffset = proof.txIndex >> level;
    const siblingOffset = ourOffset ^ 1;
    const sibEntry =
      node === "*"
        ? { offset: siblingOffset, duplicate: true }
        : { offset: siblingOffset, hash: node };

    if (level === 0) {
      const entries = [
        { offset: proof.txIndex, hash: txid, txid: true },
        sibEntry,
      ];
      entries.sort((a, b) => a.offset - b.offset);
      path.push(entries);
    } else {
      path.push([sibEntry]);
    }
  }

  return new MerklePath(blockHeight, path);
}

export interface ProofFetcherDeps {
  /** Override the @bsv/sdk Transaction.fromHex used internally. Tests inject. */
  transactionFromHex?: (hex: string) => Transaction;
}

/**
 * Fetch and assemble the SPV proof payload for a single UTXO.
 *
 * @throws ProofFetchError when the tx is unconfirmed (WoC returns no proof)
 *         or when any sub-fetch fails.
 */
export async function fetchInputProof(
  woc: WocClient,
  txid: string,
  deps: ProofFetcherDeps = {},
): Promise<InputProof> {
  const rawHex = await woc.getTxHex(txid);
  const proof = await woc.getTxProof(txid);
  if (!proof) {
    throw new ProofFetchError(
      `no proof for ${txid} — input must be confirmed before signing`,
    );
  }
  const header = await woc.getHeaderByHash(proof.blockHash);

  const mp = tscProofToMerklePath(proof, txid, header.height);

  // Self-check: the path we built must produce the same Merkle root the
  // header advertises. Catches every off-by-one in the proof conversion.
  const computedRoot = mp.computeRoot(txid).toLowerCase();
  const headerRoot = header.merkleroot.toLowerCase().replace(/^0x/, "");
  if (computedRoot !== headerRoot) {
    throw new ProofFetchError(
      `merkle root mismatch: computed ${computedRoot} != header.merkleroot ${headerRoot}`,
    );
  }

  const txFromHex = deps.transactionFromHex ?? ((h: string) => Transaction.fromHex(h));
  const tx = txFromHex(rawHex);
  tx.merklePath = mp;

  return {
    beef: tx.toBEEFUint8Array(),
    atomicBeef: new Uint8Array(tx.toAtomicBEEF()),
    merklePath: mp.toBinaryUint8Array(),
    height: header.height,
    merkleRoot: header.merkleroot,
  };
}

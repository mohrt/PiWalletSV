/**
 * Assemble an `unsigned_proposal` envelope from already-fetched primitives.
 *
 * `buildUnsignedProposal` is a *pure* function: no network, no derivation
 * surprises. It takes everything it needs as input (selected UTXOs +
 * pre-fetched proofs, recipient script, change script, change derivation,
 * fee rate, locktime, validated header chain) and returns the typed
 * `UnsignedProposalT` envelope ready for `encodeEnvelope`.
 *
 * The fetch and BEEF construction happen in
 * `lib/proof-fetcher.fetchInputProof` upstream; the header chain comes
 * from {@link "./headers.js".ensureChain} which both fetches headers
 * from WoC and PoW-validates them locally before they are pinned into
 * the envelope (so a misbehaving WoC mirror surfaces *before* we ship
 * the proposal across the QR boundary).
 *
 * v1 protocol mandates an explicit change output — the signer's verifier
 * (`piwallet/core/verify.py`) unconditionally re-derives the script at
 * `outputs[changeIndex]` from `changeDerivation` and rejects mismatches.
 * Callers that cannot leave above-dust change should fail earlier
 * (coin selection raises `CoinSelectError`), not by emitting an envelope
 * the Pi will refuse.
 */
import { P2PKH } from "@bsv/sdk";

import {
  KIND_PROPOSAL,
  type ProposalInputT,
  type ProposalOutputT,
  type UnsignedProposalT,
} from "./envelope.js";
import { HEADER_SIZE } from "./headers.js";
import type { InputProof } from "./proof-fetcher.js";

export class ProposalBuilderError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ProposalBuilderError";
  }
}

export interface ProposalInputArgs {
  txid: string;
  vout: number;
  sats: number;
  derivation: [number, number];
  proof: InputProof;
}

export interface BuildProposalArgs {
  /** 4-byte wallet self-fingerprint, hex. */
  walletFingerprintHex: string;
  /** Selected, proven inputs. */
  inputs: ProposalInputArgs[];
  /** Recipient address (P2PKH) and amount. */
  recipientAddress: string;
  recipientSats: number;
  /** Change address (already derived from `<xpub>/<change>/<index>`). Required in v1. */
  changeAddress: string;
  /** Change amount in sats; must be ≥ the dust threshold. */
  changeSats: number;
  /** BIP32 sub-derivation of the change output, e.g. `[1, 5]`. */
  changeDerivation: [number, number];
  /** sats per 1000 bytes; persisted on the envelope. */
  feeRateSatskb: number;
  locktime?: number;
  /**
   * Height of the firmware checkpoint the ``headers`` chain links
   * back to. Both sides MUST agree; the companion picks this from
   * {@link "./headers.js".checkpointFor} when assembling the
   * proposal so the Pi rejects a stale or wrong-network chain at
   * the first comparison.
   */
  checkpointHeight: number;
  /**
   * Contiguous list of 80-byte headers in ascending height order,
   * starting at ``checkpointHeight + 1``. The Pi PoW-validates this
   * chain on receipt; producing a passing chain is the companion's
   * end-to-end responsibility (see {@link "./headers.js".ensureChain}).
   */
  headers: Uint8Array[];
}

function hexToBytes(hex: string): Uint8Array {
  if (hex.length % 2 !== 0) throw new ProposalBuilderError(`odd hex length: ${hex}`);
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) {
    const byte = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
    if (Number.isNaN(byte)) throw new ProposalBuilderError(`bad hex: ${hex}`);
    out[i] = byte;
  }
  return out;
}

function p2pkhLockHex(address: string): string {
  return new P2PKH().lock(address).toHex();
}

/**
 * Build an UnsignedProposal envelope from selected UTXOs + their proofs.
 *
 * The output order is fixed at `[recipient, change]`; `changeIndex` is
 * therefore always `1` (= `outputs.length - 1`) in v1.
 */
export function buildUnsignedProposal(args: BuildProposalArgs): UnsignedProposalT {
  if (!/^[0-9a-fA-F]{8}$/.test(args.walletFingerprintHex)) {
    throw new ProposalBuilderError(
      `walletFingerprintHex must be 4 bytes (8 hex chars), got "${args.walletFingerprintHex}"`,
    );
  }
  if (args.inputs.length === 0) {
    throw new ProposalBuilderError("at least one input is required");
  }
  if (!Number.isInteger(args.recipientSats) || args.recipientSats <= 0) {
    throw new ProposalBuilderError("recipientSats must be a positive integer");
  }
  if (!Number.isInteger(args.changeSats) || args.changeSats <= 0) {
    throw new ProposalBuilderError(
      "changeSats must be a positive integer; v1 proposals MUST carry an explicit change output",
    );
  }
  if (
    !Array.isArray(args.changeDerivation) ||
    args.changeDerivation.length !== 2 ||
    !Number.isInteger(args.changeDerivation[0]) ||
    !Number.isInteger(args.changeDerivation[1]) ||
    args.changeDerivation[0] < 0 ||
    args.changeDerivation[1] < 0
  ) {
    throw new ProposalBuilderError(
      `changeDerivation must be a [branch, index] pair of non-negative integers, got ${JSON.stringify(
        args.changeDerivation,
      )}`,
    );
  }
  if (typeof args.changeAddress !== "string" || args.changeAddress.length === 0) {
    throw new ProposalBuilderError("changeAddress is required");
  }
  if (
    !Number.isInteger(args.checkpointHeight) ||
    args.checkpointHeight < 0
  ) {
    throw new ProposalBuilderError(
      `checkpointHeight must be a non-negative integer, got ${args.checkpointHeight}`,
    );
  }
  if (!Array.isArray(args.headers) || args.headers.length === 0) {
    throw new ProposalBuilderError(
      "headers must be a non-empty list of 80-byte block headers " +
        "(call ensureChain to build it)",
    );
  }
  for (let i = 0; i < args.headers.length; i++) {
    const h = args.headers[i];
    if (!(h instanceof Uint8Array) || h.length !== HEADER_SIZE) {
      throw new ProposalBuilderError(
        `headers[${i}] must be ${HEADER_SIZE} bytes`,
      );
    }
  }

  // The deepest input height must be covered by the chain we're
  // shipping; if not, the Pi will reject with "input too shallow".
  // Catch it here so the user sees a clear "chain not deep enough"
  // surface from the companion rather than a Pi-side reject coming
  // back over the QR.
  const chainTipHeight = args.checkpointHeight + args.headers.length;
  for (const i of args.inputs) {
    if (i.proof.height <= 0) {
      throw new ProposalBuilderError(
        `input ${i.txid}:${i.vout} has no confirmed height (${i.proof.height})`,
      );
    }
    if (i.proof.height < args.checkpointHeight + 1) {
      throw new ProposalBuilderError(
        `input ${i.txid}:${i.vout} at height ${i.proof.height} is older than ` +
          `the firmware checkpoint at height ${args.checkpointHeight}; ` +
          `rotate the checkpoint or pick a different UTXO`,
      );
    }
    if (i.proof.height > chainTipHeight) {
      throw new ProposalBuilderError(
        `input ${i.txid}:${i.vout} at height ${i.proof.height} exceeds chain tip ${chainTipHeight}`,
      );
    }
  }

  const walletFp = hexToBytes(args.walletFingerprintHex);

  const inputs: ProposalInputT[] = args.inputs.map((i) => ({
    txid: i.txid,
    vout: i.vout,
    sats: i.sats,
    derivation: i.derivation,
    beef: i.proof.beef,
  }));

  const outputs: ProposalOutputT[] = [
    { sats: args.recipientSats, scriptHex: p2pkhLockHex(args.recipientAddress) },
    { sats: args.changeSats, scriptHex: p2pkhLockHex(args.changeAddress) },
  ];

  return {
    kind: KIND_PROPOSAL,
    walletFp,
    inputs,
    outputs,
    changeIndex: outputs.length - 1,
    changeDerivation: args.changeDerivation,
    feeRate: args.feeRateSatskb,
    locktime: args.locktime ?? 0,
    checkpointHeight: args.checkpointHeight,
    headers: args.headers,
  };
}

/**
 * Assemble an `unsigned_proposal` envelope from already-fetched primitives.
 *
 * `buildUnsignedProposal` is a *pure* function: no network, no derivation
 * surprises. It takes everything it needs as input (selected UTXOs +
 * pre-fetched proofs, recipient script, change script, change derivation,
 * fee rate, locktime) and returns the typed `UnsignedProposalT` envelope
 * ready for `encodeEnvelope`.
 *
 * The fetch and BEEF construction happen in
 * `lib/proof-fetcher.fetchInputProof` upstream. Each `InputProof`
 * already carries the funding block's Merkle root (sourced from
 * WhatsOnChain), which we transcribe into the envelope's
 * `headerAnchors` map. The Pi takes this map on faith — see
 * `docs/protocol/spv.md` for the trust-model rationale.
 *
 * The protocol mandates an explicit change output — the signer's
 * verifier (`piwallet/core/verify.py`) unconditionally re-derives the
 * script at `outputs[changeIndex]` from `changeDerivation` and rejects
 * mismatches. Callers that cannot leave above-dust change should fail
 * earlier (coin selection raises `CoinSelectError`), not by emitting
 * an envelope the Pi will refuse.
 */
import { P2PKH } from "@bsv/sdk";

import {
  KIND_PROPOSAL,
  type ProposalInputT,
  type ProposalOutputT,
  type UnsignedProposalT,
} from "./envelope.js";
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

  // Every input must carry a confirmed height + Merkle root; the
  // anchor map below is just the deduplicated cross-product of those.
  for (const i of args.inputs) {
    if (i.proof.height <= 0) {
      throw new ProposalBuilderError(
        `input ${i.txid}:${i.vout} has no confirmed height (${i.proof.height})`,
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

  // Build the height -> raw 32-byte merkle root map. The proof's
  // ``merkleRoot`` is in displayed (big-endian hex) form; the
  // envelope encodes the byte-reversed (raw) form so it lines up
  // with what the bsv-sdk's ``MerklePath.computeRoot`` produces
  // after a tail byte-reversal (i.e. the same convention the Pi's
  // verifier uses).
  const headerAnchors = new Map<number, Uint8Array>();
  for (const i of args.inputs) {
    const rootHex = i.proof.merkleRoot.toLowerCase().replace(/^0x/, "");
    if (!/^[0-9a-f]{64}$/.test(rootHex)) {
      throw new ProposalBuilderError(
        `input ${i.txid}:${i.vout} has malformed merkleRoot ${JSON.stringify(i.proof.merkleRoot)}`,
      );
    }
    const rootRaw = hexToBytes(rootHex).reverse();
    const existing = headerAnchors.get(i.proof.height);
    if (existing === undefined) {
      headerAnchors.set(i.proof.height, rootRaw);
    } else {
      // Two inputs claiming the same block must agree on the root.
      // Disagreement here means the explorer gave us inconsistent
      // data and we should not ship the proposal.
      for (let j = 0; j < 32; j++) {
        if (existing[j] !== rootRaw[j]) {
          throw new ProposalBuilderError(
            `inputs at height ${i.proof.height} disagree on merkle root`,
          );
        }
      }
    }
  }

  return {
    kind: KIND_PROPOSAL,
    walletFp,
    inputs,
    outputs,
    changeIndex: outputs.length - 1,
    changeDerivation: args.changeDerivation,
    feeRate: args.feeRateSatskb,
    locktime: args.locktime ?? 0,
    headerAnchors,
  };
}

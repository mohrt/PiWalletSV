/**
 * Summarize a signed transaction for the companion Ready-to-broadcast UI.
 *
 * Values always come from the parsed transaction (trusted wire bytes), never
 * from the pre-sign proposal summary alone. When a proposal summary is
 * present, it must match or broadcast is refused.
 */
import type { Transaction } from "@bsv/sdk/transaction";

import { addressFromP2pkhLockHex } from "./derive.js";
import type { NetworkT } from "./envelope.js";

export type SignedTxDisplaySummary = {
  recipient: string;
  sats: number;
  feeSats: number | null;
};

export type ProposalSendSummary = {
  recipient: string;
  sats: number;
  feeSats: number;
};

/**
 * Companion v1: recipient is output 0; change is typically last.
 * Fee is derived when every input carries a sourceTransaction with values.
 */
export function summarizeSignedTxForDisplay(
  tx: Transaction,
  network: NetworkT = "main",
): SignedTxDisplaySummary | null {
  const outs = tx.outputs ?? [];
  if (outs.length < 1) return null;
  const scriptHex = outs[0]?.lockingScript?.toHex?.() ?? "";
  const recipient = addressFromP2pkhLockHex(scriptHex, network);
  if (!recipient) return null;
  if (outs[0]?.satoshis == null) return null;
  const sats = Number(outs[0].satoshis);
  if (!Number.isFinite(sats) || sats < 0) return null;

  let feeSats: number | null = null;
  const inputs = tx.inputs ?? [];
  if (inputs.length > 0) {
    let inSum = 0;
    let complete = true;
    for (const inp of inputs) {
      const srcOuts = inp.sourceTransaction?.outputs;
      const idx = inp.sourceOutputIndex;
      const prev = srcOuts?.[idx];
      if (prev?.satoshis == null) {
        complete = false;
        break;
      }
      inSum += Number(prev.satoshis);
    }
    if (complete) {
      const outSum = outs.reduce((acc, o) => acc + Number(o.satoshis ?? 0), 0);
      feeSats = inSum - outSum;
    }
  }

  return { recipient, sats, feeSats };
}

/**
 * When the companion built this send, the signed tx must match the proposal
 * recipient and amount (and fee when both sides know it).
 */
export function signedTxMatchesProposal(
  fromTx: SignedTxDisplaySummary,
  proposal: ProposalSendSummary,
): { ok: true } | { ok: false; reason: string } {
  if (fromTx.recipient !== proposal.recipient) {
    return {
      ok: false,
      reason:
        "signed transaction destination does not match the proposal — refusing broadcast",
    };
  }
  if (fromTx.sats !== proposal.sats) {
    return {
      ok: false,
      reason:
        "signed transaction amount does not match the proposal — refusing broadcast",
    };
  }
  if (fromTx.feeSats != null && fromTx.feeSats !== proposal.feeSats) {
    return {
      ok: false,
      reason:
        "signed transaction fee does not match the proposal — refusing broadcast",
    };
  }
  return { ok: true };
}

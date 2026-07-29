import { describe, expect, it } from "vitest";

import {
  signedTxMatchesProposal,
  type SignedTxDisplaySummary,
} from "../src/lib/signed-tx-summary.js";

describe("signedTxMatchesProposal", () => {
  const fromTx: SignedTxDisplaySummary = {
    recipient: "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2",
    sats: 30_000,
    feeSats: 500,
  };

  it("accepts an exact match", () => {
    expect(
      signedTxMatchesProposal(fromTx, {
        recipient: fromTx.recipient,
        sats: fromTx.sats,
        feeSats: 500,
      }),
    ).toEqual({ ok: true });
  });

  it("rejects a destination mismatch", () => {
    const got = signedTxMatchesProposal(fromTx, {
      recipient: "1CounterpartyXXXXXXXXXXXXXXXUWLpVr",
      sats: fromTx.sats,
      feeSats: 500,
    });
    expect(got.ok).toBe(false);
    if (!got.ok) expect(got.reason).toMatch(/destination/i);
  });

  it("rejects an amount mismatch", () => {
    const got = signedTxMatchesProposal(fromTx, {
      recipient: fromTx.recipient,
      sats: 29_999,
      feeSats: 500,
    });
    expect(got.ok).toBe(false);
    if (!got.ok) expect(got.reason).toMatch(/amount/i);
  });

  it("rejects a fee mismatch when the tx fee is known", () => {
    const got = signedTxMatchesProposal(fromTx, {
      recipient: fromTx.recipient,
      sats: fromTx.sats,
      feeSats: 501,
    });
    expect(got.ok).toBe(false);
    if (!got.ok) expect(got.reason).toMatch(/fee/i);
  });

  it("skips fee comparison when the tx fee could not be derived", () => {
    expect(
      signedTxMatchesProposal(
        { ...fromTx, feeSats: null },
        { recipient: fromTx.recipient, sats: fromTx.sats, feeSats: 999 },
      ),
    ).toEqual({ ok: true });
  });
});

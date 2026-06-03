import { describe, expect, it } from "vitest";

import { noSpendableUtxosMessage, splitConfirmedPending } from "../src/lib/balance-split.js";

/**
 * Pin the wallet-detail card's confirmed/pending split — drives both
 * the headline "pending" pill and the optional sub-line that shows
 * "X confirmed · Y pending" when a wallet straddles the mempool
 * boundary.
 */
describe("splitConfirmedPending", () => {
  it("returns zeros + no pending for an empty list", () => {
    expect(splitConfirmedPending([])).toEqual({
      confirmedSats: 0,
      pendingSats: 0,
      hasPending: false,
      allPending: false,
    });
  });

  it("classifies all-confirmed UTXOs cleanly", () => {
    const split = splitConfirmedPending([
      { sats: 1000, height: 800001 },
      { sats: 2500, height: 800010 },
    ]);
    expect(split.confirmedSats).toBe(3500);
    expect(split.pendingSats).toBe(0);
    expect(split.hasPending).toBe(false);
    expect(split.allPending).toBe(false);
  });

  it("treats height === 0 as pending", () => {
    const split = splitConfirmedPending([
      { sats: 10000, height: 0 },
      { sats: 20000, height: 0 },
    ]);
    expect(split.confirmedSats).toBe(0);
    expect(split.pendingSats).toBe(30000);
    expect(split.hasPending).toBe(true);
    expect(split.allPending).toBe(true);
  });

  it("splits a mixed set and reports hasPending=true, allPending=false", () => {
    // The exact case the operator hits right after a fresh broadcast:
    // their existing change UTXO (confirmed) sits next to a brand-new
    // mempool inbound. The card should show both totals so they know
    // which slice is in-flight.
    const split = splitConfirmedPending([
      { sats: 89791, height: 1735644 },
      { sats: 20000, height: 0 },
    ]);
    expect(split).toEqual({
      confirmedSats: 89791,
      pendingSats: 20000,
      hasPending: true,
      allPending: false,
    });
  });

  it("treats negative or NaN height defensively as pending", () => {
    // No realistic source produces these, but the conservative call
    // is to flag unknown-height entries as pending rather than
    // silently counting them as confirmed (which would mislead).
    const split = splitConfirmedPending([
      { sats: 100, height: -1 },
      { sats: 200, height: Number.NaN },
    ]);
    expect(split.confirmedSats).toBe(0);
    expect(split.pendingSats).toBe(300);
    expect(split.hasPending).toBe(true);
    expect(split.allPending).toBe(true);
  });

  it("does not mutate the input array", () => {
    const utxos = [
      { sats: 100, height: 100 },
      { sats: 200, height: 0 },
    ];
    const before = JSON.stringify(utxos);
    splitConfirmedPending(utxos);
    expect(JSON.stringify(utxos)).toBe(before);
  });

  it("noSpendableUtxosMessage explains mempool-only balance", () => {
    const msg = noSpendableUtxosMessage(
      [{ sats: 5000, height: 0 }],
      (n) => `${n} sats`,
    );
    expect(msg).toContain("5000 sats");
    expect(msg).toContain("mempool");
  });
});

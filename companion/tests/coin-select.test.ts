import { describe, expect, it } from "vitest";

import {
  CoinSelectError,
  DUST_THRESHOLD_SATS,
  estimateFee,
  estimateTxBytes,
  computeMaxSendSats,
  selectUtxosGreedy,
} from "../src/lib/coin-select.js";

const u = (txid: string, sats: number) => ({
  txid,
  vout: 0,
  sats,
  derivation: [0, 0] as [number, number],
});

describe("estimateTxBytes / estimateFee", () => {
  it("1 input + 1 output is 192 bytes", () => {
    expect(estimateTxBytes(1, 1)).toBe(10 + 148 + 34);
  });

  it("fee at 500 sat/kB on 1-in/2-out tx", () => {
    expect(estimateFee(1, 2, 500)).toBe(Math.ceil((10 + 148 + 68) * 500 / 1000));
  });

  it("rounds fee up (ceil)", () => {
    // 226 bytes * 1 sat/kB = 0.226 sats -> ceil(0.226) = 1
    expect(estimateFee(1, 2, 1)).toBe(1);
  });
});

describe("selectUtxosGreedy", () => {
  it("uses one UTXO when it fully covers target + fee + above-dust change", () => {
    const res = selectUtxosGreedy([u("a".repeat(64), 100_000)], 30_000, 500);
    expect(res.inputs).toHaveLength(1);
    expect(res.totalInputSats).toBe(100_000);
    expect(res.changeSats).toBe(100_000 - 30_000 - res.feeSats);
    expect(res.changeSats).toBeGreaterThanOrEqual(DUST_THRESHOLD_SATS);
    expect(res.estimatedBytes).toBe(estimateTxBytes(1, 2));
  });

  it("aggregates multiple UTXOs largest-first", () => {
    const res = selectUtxosGreedy(
      [u("a".repeat(64), 20_000), u("b".repeat(64), 15_000), u("c".repeat(64), 10_000)],
      40_000,
      500,
    );
    expect(res.inputs.map((i) => i.sats)).toEqual([20_000, 15_000, 10_000]);
    expect(res.totalInputSats).toBe(45_000);
    expect(res.changeSats).toBeGreaterThanOrEqual(DUST_THRESHOLD_SATS);
  });

  it("keeps adding UTXOs when the running change would be dust", () => {
    // First UTXO alone would leave change below dust; selector must pull
    // in a second UTXO to push the residue above the threshold.
    const utxos = [
      u("a".repeat(64), 10_000),
      u("b".repeat(64), 5_000),
    ];
    const res = selectUtxosGreedy(utxos, 9_700, 500);
    expect(res.inputs).toHaveLength(2);
    expect(res.changeSats).toBeGreaterThanOrEqual(DUST_THRESHOLD_SATS);
  });

  it("rejects selections that cannot leave above-dust change", () => {
    // Single UTXO whose residue after fee falls below dust; no other
    // UTXOs available to top it up.
    expect(() =>
      selectUtxosGreedy([u("a".repeat(64), 10_000)], 9_700, 500, DUST_THRESHOLD_SATS),
    ).toThrow(/insufficient funds.*above-dust change/);
  });

  it("throws if no combination covers target + fee", () => {
    expect(() =>
      selectUtxosGreedy(
        [u("a".repeat(64), 1_000), u("b".repeat(64), 500)],
        10_000,
        500,
      ),
    ).toThrow(CoinSelectError);
  });

  it("rejects empty utxo list", () => {
    expect(() => selectUtxosGreedy([], 100, 500)).toThrow(/no UTXOs/);
  });

  it("rejects non-positive target", () => {
    expect(() => selectUtxosGreedy([u("a".repeat(64), 100)], 0, 500)).toThrow(
      /targetSats/,
    );
    expect(() => selectUtxosGreedy([u("a".repeat(64), 100)], -1, 500)).toThrow(
      /targetSats/,
    );
  });

  it("rejects negative fee rate", () => {
    expect(() => selectUtxosGreedy([u("a".repeat(64), 100)], 50, -1)).toThrow(
      /feeRateSatskb/,
    );
  });

  it("zero-fee rate still selects (covers + 0)", () => {
    const res = selectUtxosGreedy([u("a".repeat(64), 10_000)], 5_000, 0);
    expect(res.feeSats).toBe(0);
    expect(res.changeSats).toBe(5_000);
  });
});

describe("computeMaxSendSats", () => {
  it("returns 0 for empty UTXO list", () => {
    expect(computeMaxSendSats([], 500)).toBe(0);
  });

  it("leaves above-dust change at the selected fee rate", () => {
    const utxos = [u("a".repeat(64), 100_000)];
    const max = computeMaxSendSats(utxos, 500);
    expect(max).toBeGreaterThan(0);
    const sel = selectUtxosGreedy(utxos, max, 500);
    expect(sel.changeSats).toBeGreaterThanOrEqual(DUST_THRESHOLD_SATS);
  });

  it("max + 1 sat fails greedy selection", () => {
    const utxos = [u("a".repeat(64), 50_000)];
    const max = computeMaxSendSats(utxos, 500);
    expect(() => selectUtxosGreedy(utxos, max + 1, 500)).toThrow(CoinSelectError);
  });
});

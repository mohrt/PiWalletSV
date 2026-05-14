import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { deriveAddress } from "../src/lib/derive.js";
import { scanWalletUtxos } from "../src/lib/utxo.js";
import {
  WocClient,
  type WocBulkUnspentResult,
  type WocUnspentEntry,
} from "../src/lib/woc.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const FIXTURE = JSON.parse(
  readFileSync(
    join(__dirname, "../../tests/fixtures/addresses_canonical.json"),
    "utf8",
  ),
) as { xpub: string };

const XPUB = FIXTURE.xpub;

function dummyClient(): WocClient {
  // Construct with a fetch that throws if accidentally called.
  return new WocClient({
    fetch: () => Promise.reject(new Error("network not allowed in tests")),
  });
}

function utxo(txid: string, vout: number, sats: number): WocUnspentEntry {
  return { txid, vout, sats, height: 812345 };
}

/**
 * Build a `fetchUnspentBatch` hook from a per-address fixture, mirroring
 * how the real `WocClient.getUnspentBatch` returns one row per address
 * in input order.
 */
function batchFromMap(
  fund: Record<string, WocUnspentEntry[]>,
): (addresses: string[]) => Promise<WocBulkUnspentResult[]> {
  return async (addresses) =>
    addresses.map((address) => ({ address, utxos: fund[address] ?? [] }));
}

describe("scanWalletUtxos", () => {
  it("returns no utxos when every probed address is empty (gap limit reached)", async () => {
    const probed: string[] = [];
    const result = await scanWalletUtxos(XPUB, dummyClient(), {
      gapLimit: 3,
      batch: 5,
      fetchUnspentBatch: async (addrs) => {
        probed.push(...addrs);
        return addrs.map((a) => ({ address: a, utxos: [] }));
      },
    });
    expect(result.utxos).toEqual([]);
    expect(result.totalSats).toBe(0);
    expect(result.lastReceiveUsed).toBe(-1);
    expect(result.lastChangeUsed).toBe(-1);
    // 3 receive + 3 change = 6 probes
    expect(probed).toHaveLength(6);
  });

  it("collects utxos on the receive branch and stops after gap", async () => {
    const u0 = utxo("aa".repeat(32), 0, 5000);
    const u2 = utxo("bb".repeat(32), 1, 12345);
    const fund: Record<string, WocUnspentEntry[]> = {
      [deriveAddress(XPUB, 0, 0).address]: [u0],
      [deriveAddress(XPUB, 0, 2).address]: [u2],
    };
    const result = await scanWalletUtxos(XPUB, dummyClient(), {
      gapLimit: 3,
      batch: 5,
      fetchUnspentBatch: batchFromMap(fund),
    });
    // After index=2 we need 3 consecutive empties (3,4,5) -> stop at 6 on receive.
    expect(result.lastReceiveUsed).toBe(2);
    expect(result.utxos).toHaveLength(2);
    expect(result.totalSats).toBe(5000 + 12345);
    expect(result.utxos[0]).toMatchObject({
      txid: "bb".repeat(32),
      vout: 1,
      sats: 12345,
      derivation: [0, 2],
    });
    expect(result.utxos[1]).toMatchObject({
      txid: "aa".repeat(32),
      vout: 0,
      sats: 5000,
      derivation: [0, 0],
    });
    expect(result.stoppedAt.receive).toBeGreaterThan(2);
  });

  it("emits progress events for every probed address", async () => {
    const calls: { branch: number; index: number; found: number }[] = [];
    await scanWalletUtxos(XPUB, dummyClient(), {
      gapLimit: 2,
      batch: 5,
      fetchUnspentBatch: async (addrs) =>
        addrs.map((a) => ({ address: a, utxos: [] })),
      onProgress: (e) =>
        calls.push({ branch: e.branch, index: e.index, found: e.found }),
    });
    expect(calls).toEqual([
      { branch: 0, index: 0, found: 0 },
      { branch: 0, index: 1, found: 0 },
      { branch: 1, index: 0, found: 0 },
      { branch: 1, index: 1, found: 0 },
    ]);
  });

  it("scans both branches and tags derivation correctly", async () => {
    const recv = utxo("aa".repeat(32), 0, 10000);
    const chng = utxo("cc".repeat(32), 0, 4000);
    const fund: Record<string, WocUnspentEntry[]> = {
      [deriveAddress(XPUB, 0, 1).address]: [recv],
      [deriveAddress(XPUB, 1, 0).address]: [chng],
    };
    const result = await scanWalletUtxos(XPUB, dummyClient(), {
      gapLimit: 2,
      batch: 5,
      fetchUnspentBatch: batchFromMap(fund),
    });
    expect(result.utxos).toHaveLength(2);
    const recvUtxo = result.utxos.find((u) => u.derivation[0] === 0)!;
    const changeUtxo = result.utxos.find((u) => u.derivation[0] === 1)!;
    expect(recvUtxo.derivation).toEqual([0, 1]);
    expect(changeUtxo.derivation).toEqual([1, 0]);
    expect(result.lastReceiveUsed).toBe(1);
    expect(result.lastChangeUsed).toBe(0);
  });

  it("multiple UTXOs at the same address are all captured", async () => {
    const a = deriveAddress(XPUB, 0, 0).address;
    const result = await scanWalletUtxos(XPUB, dummyClient(), {
      gapLimit: 1,
      batch: 1,
      fetchUnspentBatch: async (addrs) =>
        addrs.map((address) => ({
          address,
          utxos:
            address === a
              ? [utxo("11".repeat(32), 0, 1000), utxo("22".repeat(32), 1, 2000)]
              : [],
        })),
    });
    expect(result.utxos.map((u) => u.sats).sort()).toEqual([1000, 2000]);
    expect(result.totalSats).toBe(3000);
  });

  it("respects startReceive / startChange hints", async () => {
    const probed: { branch: number; index: number }[] = [];
    await scanWalletUtxos(XPUB, dummyClient(), {
      gapLimit: 2,
      batch: 5,
      startReceive: 7,
      startChange: 3,
      fetchUnspentBatch: async (addrs) =>
        addrs.map((a) => ({ address: a, utxos: [] })),
      onProgress: (e) => probed.push({ branch: e.branch, index: e.index }),
    });
    expect(probed[0]).toEqual({ branch: 0, index: 7 });
    // The receive branch probes [7,8] (gap=2). Then change starts at index 3.
    expect(probed.find((p) => p.branch === 1)?.index).toBe(3);
  });

  it("uses one bulk call per branch when wallet is empty (default batch)", async () => {
    const callSizes: number[] = [];
    await scanWalletUtxos(XPUB, dummyClient(), {
      gapLimit: 20,
      // Default batch (== WOC_BULK_BATCH_MAX, 20) so the empty-wallet
      // case turns into exactly 2 bulk calls — the whole point of
      // adopting the bulk endpoint.
      fetchUnspentBatch: async (addrs) => {
        callSizes.push(addrs.length);
        return addrs.map((a) => ({ address: a, utxos: [] }));
      },
    });
    expect(callSizes).toEqual([20, 20]);
  });

  it("clamps batch sizes above WOC_BULK_BATCH_MAX", async () => {
    const callSizes: number[] = [];
    await scanWalletUtxos(XPUB, dummyClient(), {
      gapLimit: 20,
      batch: 100, // caller passes more than the WoC bulk cap
      fetchUnspentBatch: async (addrs) => {
        callSizes.push(addrs.length);
        return addrs.map((a) => ({ address: a, utxos: [] }));
      },
    });
    // Each call should be clamped at 20.
    expect(callSizes.every((n) => n <= 20)).toBe(true);
    expect(callSizes).toEqual([20, 20]);
  });

  it("counts a mempool-only UTXO (height=0) toward the wallet balance", async () => {
    // Regression for the "fresh broadcast → recipient shows 0 balance"
    // bug. WoC's older `POST /addresses/unspent` was mempool-blind,
    // so a tx that just landed in WoC's mempool wouldn't count until
    // it confirmed (sometimes minutes). The fix wires
    // `WocClient.getUnspentBatch` to the split confirmed/unconfirmed
    // endpoints and merges them; this test pins the contract that
    // `scanWalletUtxos` honours `height: 0` rows the same as
    // confirmed ones — they're spendable (or at least visible) and
    // belong in the balance.
    const recvAddr0 = deriveAddress(XPUB, 0, 0).address;
    const fund: Record<string, WocUnspentEntry[]> = {
      [recvAddr0]: [
        { txid: "ee".repeat(32), vout: 0, sats: 10000, height: 0 },
      ],
    };
    const result = await scanWalletUtxos(XPUB, dummyClient(), {
      gapLimit: 3,
      batch: 5,
      fetchUnspentBatch: batchFromMap(fund),
    });
    expect(result.totalSats).toBe(10000);
    expect(result.utxos).toHaveLength(1);
    expect(result.utxos[0]).toMatchObject({
      txid: "ee".repeat(32),
      vout: 0,
      sats: 10000,
      height: 0,
      derivation: [0, 0],
    });
    expect(result.lastReceiveUsed).toBe(0);
  });
});

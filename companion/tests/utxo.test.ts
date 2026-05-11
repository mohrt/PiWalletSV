import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { deriveAddress } from "../src/lib/derive.js";
import { scanWalletUtxos } from "../src/lib/utxo.js";
import { WocClient, type WocUnspentEntry } from "../src/lib/woc.js";

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

describe("scanWalletUtxos", () => {
  it("returns no utxos when every probed address is empty (gap limit reached)", async () => {
    const probed: string[] = [];
    const result = await scanWalletUtxos(XPUB, dummyClient(), {
      gapLimit: 3,
      batch: 5,
      fetchUnspent: async (addr) => {
        probed.push(addr);
        return [];
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
      fetchUnspent: async (a) => fund[a] ?? [],
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
      fetchUnspent: async () => [],
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
      fetchUnspent: async (a) => fund[a] ?? [],
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
      fetchUnspent: async (addr) => {
        if (addr !== a) return [];
        return [utxo("11".repeat(32), 0, 1000), utxo("22".repeat(32), 1, 2000)];
      },
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
      fetchUnspent: async () => [],
      onProgress: (e) => probed.push({ branch: e.branch, index: e.index }),
    });
    expect(probed[0]).toEqual({ branch: 0, index: 7 });
    // The receive branch probes [7,8] (gap=2). Then change starts at index 3.
    expect(probed.find((p) => p.branch === 1)?.index).toBe(3);
  });
});

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it, vi } from "vitest";

import { BitailsClient } from "../src/lib/bitails.js";
import { deriveAddress } from "../src/lib/derive.js";
import {
  enrichWalletTxFromWoc,
  fetchWalletHistory,
  historyBranchEnd,
  mergeHistoryEntries,
} from "../src/lib/history.js";
import { DEFAULT_GAP_LIMIT } from "../src/lib/utxo.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const FIXTURE = JSON.parse(
  readFileSync(
    join(__dirname, "../../tests/fixtures/addresses_canonical.json"),
    "utf8",
  ),
) as { xpub: string };

const XPUB = FIXTURE.xpub;

describe("historyBranchEnd", () => {
  it("uses stoppedAt + lookahead when present", () => {
    expect(historyBranchEnd(25, -1, 5)).toBe(30);
  });

  it("falls back to gap limit when stoppedAt is absent", () => {
    expect(historyBranchEnd(undefined, -1, 5)).toBe(DEFAULT_GAP_LIMIT + 5);
  });

  it("falls back to lastUsed + lookahead when higher than gap", () => {
    expect(historyBranchEnd(undefined, 30, 5)).toBe(36);
  });
});

describe("fetchWalletHistory", () => {
  it("queries full stoppedAt range for spent-only wallets", async () => {
    const addr0 = deriveAddress(XPUB, 0, 0).address;
    const getHistoryBatch = vi.fn(async (addresses: string[]) => {
      if (addresses.includes(addr0)) {
        return [
          {
            txid: "aa".repeat(32),
            timestamp: 1_700_000_000,
            blockHeight: 812345,
            deltaSats: 50_000,
          },
        ];
      }
      return [];
    });
    const bitails = { getHistoryBatch } as unknown as BitailsClient;

    const snap = await fetchWalletHistory(XPUB, bitails, {
      stoppedAtReceive: 25,
      stoppedAtChange: 20,
      lastReceiveUsed: -1,
      lastChangeUsed: -1,
      lookahead: 0,
    });

    expect(snap.entries).toHaveLength(1);
    expect(snap.entries[0].deltaSats).toBe(50_000);
    expect(snap.addressesQueried).toBe(45);
    const queried = getHistoryBatch.mock.calls.flatMap((c) => c[0] as string[]);
    expect(queried).toContain(addr0);
    expect(queried).toHaveLength(45);
  });

  it("queries beyond lastReceiveUsed when stoppedAt is higher", async () => {
    const getHistoryBatch = vi.fn(async () => []);
    const bitails = { getHistoryBatch } as unknown as BitailsClient;

    await fetchWalletHistory(XPUB, bitails, {
      stoppedAtReceive: 26,
      lastReceiveUsed: 5,
      stoppedAtChange: 20,
      lastChangeUsed: -1,
      lookahead: 0,
    });

    expect(snapAddressesQueried(getHistoryBatch)).toBe(46);
  });

  it("merges duplicate txids across batches", async () => {
    const txid = "bb".repeat(32);
    let call = 0;
    const getHistoryBatch = vi.fn(async () => {
      call += 1;
      if (call === 1) {
        return [{ txid, timestamp: 100, blockHeight: 100, deltaSats: 1000 }];
      }
      if (call === 2) {
        return [{ txid, timestamp: 100, blockHeight: 100, deltaSats: 500 }];
      }
      return [];
    });
    const bitails = { getHistoryBatch } as unknown as BitailsClient;

    const snap = await fetchWalletHistory(XPUB, bitails, {
      stoppedAtReceive: 25,
      stoppedAtChange: 25,
      lookahead: 0,
    });

    expect(getHistoryBatch).toHaveBeenCalledTimes(3);
    expect(snap.entries).toHaveLength(1);
    expect(snap.entries[0].deltaSats).toBe(1500);
  });

  it("uses legacy fallback range without stoppedAt", async () => {
    const getHistoryBatch = vi.fn(async () => []);
    const bitails = { getHistoryBatch } as unknown as BitailsClient;

    await fetchWalletHistory(XPUB, bitails, {
      lastReceiveUsed: -1,
      lastChangeUsed: -1,
      lookahead: 5,
    });

    expect(snapAddressesQueried(getHistoryBatch)).toBe(
      2 * (DEFAULT_GAP_LIMIT + 5),
    );
  });

  it("batches addresses in groups of 20", async () => {
    const getHistoryBatch = vi.fn(async () => []);
    const bitails = { getHistoryBatch } as unknown as BitailsClient;

    await fetchWalletHistory(XPUB, bitails, {
      stoppedAtReceive: 25,
      stoppedAtChange: 20,
      lookahead: 0,
    });

    expect(getHistoryBatch).toHaveBeenCalledTimes(3);
    const calls = getHistoryBatch.mock.calls as unknown as [string[]][];
    const sizes = calls.map((c) => c[0].length);
    expect(sizes).toEqual([20, 20, 5]);
  });

  it("uses WoC for testnet instead of Bitails", async () => {
    const getHistoryBatch = vi.fn(async () => {
      throw new Error("Bitails should not be called on testnet");
    });
    const bitails = { getHistoryBatch } as unknown as BitailsClient;
    const txid = "dd".repeat(32);
    const prevTxid = "ee".repeat(32);
    const addr0 = deriveAddress(XPUB, 0, 0, "test").address;
    const getAddressHistoryBatch = vi.fn(async (addresses: string[]) =>
      addresses.map((address) => ({
        address,
        entries: address === addr0
          ? [{ txid, blockHeight: 12345 }]
          : [],
      })),
    );
    const getTxDetail = vi.fn(async (id: string) => {
      if (id === txid) {
        return {
          txid,
          time: 1_700_000_000,
          blockHeight: 12345,
          vin: [{ txid: prevTxid, vout: 0 }],
          vout: [{ valueBsv: 0.00002, address: addr0 }],
        };
      }
      if (id === prevTxid) {
        return {
          txid: prevTxid,
          time: 1_699_000_000,
          blockHeight: 12300,
          vin: [],
          vout: [{ valueBsv: 0.00005, address: addr0 }],
        };
      }
      throw new Error(`unexpected tx ${id}`);
    });
    const woc = { getAddressHistoryBatch, getTxDetail } as unknown as import("../src/lib/woc.js").WocClient;

    const snap = await fetchWalletHistory(XPUB, bitails, {
      network: "test",
      woc,
      stoppedAtReceive: 3,
      stoppedAtChange: 2,
      lookahead: 0,
    });

    expect(getHistoryBatch).not.toHaveBeenCalled();
    expect(getAddressHistoryBatch).toHaveBeenCalled();
    expect(getTxDetail).toHaveBeenCalled();
    expect(snap.entries).toEqual([
      {
        txid,
        timestamp: 1_700_000_000,
        blockHeight: 12345,
        deltaSats: 2000 - 5000,
        deltaKnown: true,
      },
    ]);
  });
});

describe("enrichWalletTxFromWoc", () => {
  it("computes net receive and send deltas from vout and prevouts", async () => {
    const walletAddr = "1Wallet";
    const txid = "ff".repeat(32);
    const prevTxid = "00".repeat(32);
    const cache = new Map();
    const getTxDetail = vi.fn(async (id: string) => {
      if (id === txid) {
        return {
          txid,
          time: 100,
          blockHeight: 10,
          vin: [{ txid: prevTxid, vout: 0 }],
          vout: [{ valueBsv: 0.00003, address: walletAddr }],
        };
      }
      return {
        txid: prevTxid,
        time: 90,
        blockHeight: 9,
        vin: [],
        vout: [{ valueBsv: 0.00001, address: walletAddr }],
      };
    });
    const woc = { getTxDetail } as unknown as import("../src/lib/woc.js").WocClient;

    const entry = await enrichWalletTxFromWoc(
      txid,
      10,
      new Set([walletAddr]),
      woc,
      cache,
    );
    expect(entry.deltaSats).toBe(3000 - 1000);
    expect(entry.deltaKnown).toBe(true);
  });
});

describe("mergeHistoryEntries", () => {
  it("sums deltaSats for duplicate txids", () => {
    const txid = "cc".repeat(32);
    const merged = mergeHistoryEntries([
      { txid, timestamp: 1, blockHeight: 10, deltaSats: 100 },
      { txid, timestamp: 1, blockHeight: 10, deltaSats: -30 },
    ]);
    expect(merged).toHaveLength(1);
    expect(merged[0].deltaSats).toBe(70);
  });
});

function snapAddressesQueried(
  getHistoryBatch: { mock: { calls: unknown[][] } },
): number {
  return getHistoryBatch.mock.calls.reduce(
    (sum, c) => sum + (c[0] as string[]).length,
    0,
  );
}

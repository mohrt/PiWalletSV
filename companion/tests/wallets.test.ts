import "fake-indexeddb/auto";

import { beforeEach, describe, expect, it } from "vitest";

import {
  WALLET_SCHEMA_VERSION,
  WalletStoreError,
  _clearAllWallets,
  addWallet,
  clearLastScan,
  findByFingerprintAndPath,
  getWallet,
  listWallets,
  removeWallet,
  setLastScan,
  setNextReceiveIndex,
  updateLabel,
  withDefaults,
} from "../src/lib/wallets.js";
import type { WalletUtxo } from "../src/lib/utxo.js";

const DEMO = {
  label: "demo wallet",
  xpub:
    "xpub6CdMDgU2hzWyeZ852LWqp5AfDz3ty2cRfi4jEw9BT8aNYugMQv" +
    "VykQsKLARZdbqKKp7yTviJdL1N9saYLmJNKD1rwVAwLTmU8r8qKeoyG4R",
  fingerprint: "cf987d8c",
  path: "m/44'/236'/0'",
};

describe("wallets store", () => {
  beforeEach(async () => {
    await _clearAllWallets();
  });

  it("adds a wallet and retrieves it by id", async () => {
    const rec = await addWallet(DEMO);
    expect(rec.id).toMatch(/[0-9a-f-]{36}/);
    expect(rec.label).toBe("demo wallet");
    expect(rec.fingerprint).toBe("cf987d8c");
    expect(rec.schemaVersion).toBe(WALLET_SCHEMA_VERSION);
    expect(typeof rec.addedAt).toBe("string");

    const fetched = await getWallet(rec.id);
    expect(fetched).not.toBeNull();
    expect(fetched!.xpub).toBe(DEMO.xpub);
  });

  it("normalizes fingerprint to lowercase", async () => {
    const rec = await addWallet({ ...DEMO, fingerprint: "CF987D8C" });
    expect(rec.fingerprint).toBe("cf987d8c");
  });

  it("rejects duplicate fingerprint+path pairs", async () => {
    await addWallet(DEMO);
    await expect(addWallet({ ...DEMO, label: "again" })).rejects.toBeInstanceOf(
      WalletStoreError,
    );
  });

  it("allows the same fingerprint on a different derivation path", async () => {
    await addWallet(DEMO);
    const second = await addWallet({ ...DEMO, path: "m/44'/0'/0'" });
    expect(second.path).toBe("m/44'/0'/0'");
  });

  it("listWallets returns newest first", async () => {
    await addWallet({ ...DEMO, fingerprint: "11111111", label: "first" });
    await new Promise((r) => setTimeout(r, 5));
    await addWallet({ ...DEMO, fingerprint: "22222222", label: "second" });
    const all = await listWallets();
    expect(all.map((w) => w.label)).toEqual(["second", "first"]);
  });

  it("findByFingerprintAndPath returns the matching record", async () => {
    await addWallet(DEMO);
    const hit = await findByFingerprintAndPath("cf987d8c", DEMO.path);
    expect(hit?.fingerprint).toBe("cf987d8c");
    const miss = await findByFingerprintAndPath("00000000", DEMO.path);
    expect(miss).toBeNull();
  });

  it("updateLabel mutates only the label field", async () => {
    const rec = await addWallet(DEMO);
    await updateLabel(rec.id, "renamed");
    const after = await getWallet(rec.id);
    expect(after?.label).toBe("renamed");
    expect(after?.xpub).toBe(DEMO.xpub);
  });

  it("removeWallet deletes by id", async () => {
    const rec = await addWallet(DEMO);
    await removeWallet(rec.id);
    expect(await getWallet(rec.id)).toBeNull();
    expect(await listWallets()).toHaveLength(0);
  });

  it("getWallet returns null for unknown id", async () => {
    expect(await getWallet("does-not-exist")).toBeNull();
  });

  it("freshly added wallet has no nextReceiveIndex; withDefaults fills it in as 0", async () => {
    const rec = await addWallet(DEMO);
    expect(rec.nextReceiveIndex).toBeUndefined();
    expect(withDefaults(rec).nextReceiveIndex).toBe(0);
  });

  it("setNextReceiveIndex persists the value", async () => {
    const rec = await addWallet(DEMO);
    await setNextReceiveIndex(rec.id, 7);
    const after = await getWallet(rec.id);
    expect(after?.nextReceiveIndex).toBe(7);
  });

  it("setNextReceiveIndex rejects out-of-range values", async () => {
    const rec = await addWallet(DEMO);
    await expect(setNextReceiveIndex(rec.id, -1)).rejects.toBeInstanceOf(
      WalletStoreError,
    );
    await expect(setNextReceiveIndex(rec.id, 0x80000000)).rejects.toBeInstanceOf(
      WalletStoreError,
    );
    await expect(setNextReceiveIndex(rec.id, 1.5)).rejects.toBeInstanceOf(
      WalletStoreError,
    );
  });

  it("setLastScan / clearLastScan round-trip", async () => {
    const rec = await addWallet(DEMO);
    expect(rec.lastScan).toBeUndefined();
    const utxo: WalletUtxo = {
      txid: "aa".repeat(32),
      vout: 0,
      sats: 5000,
      height: 812345,
      address: "1K6LZdwpKT5XkEZo2T2kW197aMXYbYMc4f",
      derivation: [0, 1],
    };
    await setLastScan(rec.id, {
      at: "2026-05-10T00:00:00.000Z",
      totalSats: 5000,
      utxos: [utxo],
      lastReceiveUsed: 1,
      lastChangeUsed: -1,
      addressesScanned: 22,
    });
    const after = await getWallet(rec.id);
    expect(after?.lastScan?.totalSats).toBe(5000);
    expect(after?.lastScan?.utxos[0]).toMatchObject({
      txid: "aa".repeat(32),
      derivation: [0, 1],
    });

    await clearLastScan(rec.id);
    const cleared = await getWallet(rec.id);
    expect(cleared?.lastScan).toBeUndefined();
  });

  it("addWallet defaults to network='main' when omitted", async () => {
    const rec = await addWallet(DEMO);
    expect(rec.network).toBe("main");
    const fetched = await getWallet(rec.id);
    expect(fetched?.network).toBe("main");
  });

  it("addWallet persists network='test' when provided", async () => {
    const rec = await addWallet({ ...DEMO, network: "test" });
    expect(rec.network).toBe("test");
    const fetched = await getWallet(rec.id);
    expect(fetched?.network).toBe("test");
  });

  it("allows a mainnet + testnet wallet for the same seed (different networks)", async () => {
    await addWallet({ ...DEMO, network: "main", label: "main" });
    const second = await addWallet({ ...DEMO, network: "test", label: "test" });
    expect(second.network).toBe("test");
    const all = await listWallets();
    expect(all).toHaveLength(2);
  });

  it("rejects duplicate fingerprint+path+network", async () => {
    await addWallet({ ...DEMO, network: "test" });
    await expect(
      addWallet({ ...DEMO, network: "test", label: "again" }),
    ).rejects.toBeInstanceOf(WalletStoreError);
  });

  it("withDefaults backfills network='main' for legacy records", () => {
    const legacy = {
      id: "x",
      label: "legacy",
      xpub: "xpub-stub",
      fingerprint: "ffffffff",
      path: "m/44'/236'/0'",
      addedAt: "2025-01-01T00:00:00.000Z",
      schemaVersion: WALLET_SCHEMA_VERSION,
    };
    const filled = withDefaults(legacy);
    expect(filled.network).toBe("main");
    expect(filled.nextReceiveIndex).toBe(0);
  });
});

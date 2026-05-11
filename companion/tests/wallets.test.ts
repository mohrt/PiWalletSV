import "fake-indexeddb/auto";

import { beforeEach, describe, expect, it } from "vitest";

import {
  WALLET_SCHEMA_VERSION,
  WalletStoreError,
  _clearAllWallets,
  addWallet,
  findByFingerprintAndPath,
  getWallet,
  listWallets,
  removeWallet,
  updateLabel,
} from "../src/lib/wallets.js";

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
});

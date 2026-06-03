import "fake-indexeddb/auto";

import { beforeEach, describe, expect, it } from "vitest";

import {
  BACKUP_FORMAT,
  BACKUP_VERSION,
  buildWalletBackupFile,
  importWalletBackup,
  serializeWalletBackup,
} from "../src/lib/wallet-backup.js";
import { WalletStoreError, _clearAllWallets, addWallet, listWallets } from "../src/lib/wallets.js";

const DEMO = {
  label: "demo wallet",
  xpub:
    "xpub6CdMDgU2hzWyeZ852LWqp5AfDz3ty2cRfi4jEw9BT8aNYugMQv" +
    "VykQsKLARZdbqKKp7yTviJdL1N9saYLmJNKD1rwVAwLTmU8r8qKeoyG4R",
  fingerprint: "cf987d8c",
  path: "m/44'/236'/0'",
};

describe("wallet backup", () => {
  beforeEach(async () => {
    await _clearAllWallets();
  });

  it("exports paired wallets as JSON with no secrets beyond xpub metadata", async () => {
    await addWallet(DEMO);
    const file = await buildWalletBackupFile();
    expect(file.format).toBe(BACKUP_FORMAT);
    expect(file.version).toBe(BACKUP_VERSION);
    expect(file.wallets).toHaveLength(1);
    expect(file.wallets[0]).toMatchObject({
      label: DEMO.label,
      xpub: DEMO.xpub,
      fingerprint: DEMO.fingerprint,
      path: DEMO.path,
    });
    expect(file.wallets[0]).not.toHaveProperty("lastScan");
    expect(file.wallets[0]).not.toHaveProperty("id");
  });

  it("round-trips import on an empty store", async () => {
    await addWallet(DEMO);
    const json = serializeWalletBackup(await buildWalletBackupFile());
    await _clearAllWallets();
    expect(await listWallets()).toHaveLength(0);

    const result = await importWalletBackup(json);
    expect(result.imported).toBe(1);
    expect(result.skippedDuplicates).toBe(0);
    expect(result.failed).toHaveLength(0);

    const all = await listWallets();
    expect(all).toHaveLength(1);
    expect(all[0].label).toBe(DEMO.label);
  });

  it("skips duplicates already on this device", async () => {
    await addWallet(DEMO);
    const json = serializeWalletBackup(await buildWalletBackupFile());
    const result = await importWalletBackup(json);
    expect(result.imported).toBe(0);
    expect(result.skippedDuplicates).toBe(1);
    expect(await listWallets()).toHaveLength(1);
  });

  it("rejects invalid JSON and wrong format", async () => {
    await expect(importWalletBackup("{")).rejects.toBeInstanceOf(WalletStoreError);
    await expect(
      importWalletBackup(JSON.stringify({ format: "other", version: 1, wallets: [] })),
    ).rejects.toBeInstanceOf(WalletStoreError);
  });

  it("records per-entry failures without aborting the rest", async () => {
    const addedAt = new Date().toISOString();
    const json = JSON.stringify({
      format: BACKUP_FORMAT,
      version: BACKUP_VERSION,
      exportedAt: addedAt,
      wallets: [
        { ...DEMO, label: "good", addedAt },
        { ...DEMO, label: "bad fp", fingerprint: "00000000", addedAt },
      ],
    });
    const result = await importWalletBackup(json);
    expect(result.imported).toBe(1);
    expect(result.failed).toHaveLength(1);
    expect(result.failed[0].label).toBe("bad fp");
  });
});

import "fake-indexeddb/auto";

import { beforeEach, describe, expect, it } from "vitest";

class MemoryStorage {
  private map = new Map<string, string>();
  get length(): number { return this.map.size; }
  clear(): void { this.map.clear(); }
  getItem(k: string): string | null { return this.map.get(k) ?? null; }
  setItem(k: string, v: string): void { this.map.set(k, String(v)); }
  removeItem(k: string): void { this.map.delete(k); }
  key(i: number): string | null {
    return Array.from(this.map.keys())[i] ?? null;
  }
}
(globalThis as unknown as { localStorage: Storage }).localStorage =
  new MemoryStorage() as unknown as Storage;

import {
  KEY_LIST_SORT,
  KEY_LIST_UNIT,
  applyCompanionSettings,
  exportCompanionSettings,
} from "../src/lib/companion-settings.js";
import {
  BACKUP_FORMAT,
  BACKUP_NEWER_THAN_APP_MSG,
  BACKUP_VERSION,
  buildWalletBackupFile,
  buildWalletBackupPw1Lines,
  formatImportWalletResult,
  importWalletBackup,
  importWalletBackupBytes,
  serializeWalletBackup,
  walletBackupJsonToPw1Lines,
  walletBackupToBytes,
} from "../src/lib/wallet-backup.js";
import { APP_VERSION } from "../src/lib/version.js";
import {
  WalletStoreError,
  _clearAllWallets,
  addWallet,
  getWallet,
  listWallets,
  setLastScan,
} from "../src/lib/wallets.js";

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
    localStorage.clear();
  });

  it("exports paired wallets as JSON with no secrets beyond xpub metadata", async () => {
    await addWallet(DEMO);
    const file = await buildWalletBackupFile({ scope: "wallets-and-settings" });
    expect(file.format).toBe(BACKUP_FORMAT);
    expect(file.version).toBe(BACKUP_VERSION);
    expect(file.companionVersion).toBe(APP_VERSION);
    expect(file.wallets).toHaveLength(1);
    expect(file.wallets[0]).toMatchObject({
      label: DEMO.label,
      xpub: DEMO.xpub,
      fingerprint: DEMO.fingerprint,
      path: DEMO.path,
    });
    expect(file.wallets[0]).not.toHaveProperty("id");
    expect(file.settings).toBeDefined();
  });

  it("exports wallets only without settings or cached snapshots", async () => {
    localStorage.setItem(KEY_LIST_SORT, "label");
    const rec = await addWallet(DEMO);
    await setLastScan(rec.id, {
      at: new Date().toISOString(),
      totalSats: 42_000,
      utxos: [],
      lastReceiveUsed: 0,
      lastChangeUsed: -1,
      addressesScanned: 20,
    });

    const file = await buildWalletBackupFile({ scope: "wallets-only" });
    expect(file.settings).toBeUndefined();
    expect(file.wallets[0].lastScan).toBeUndefined();
    expect(localStorage.getItem(KEY_LIST_SORT)).toBe("label");
  });

  it("includes companion settings and cached wallet state when scope is full", async () => {
    localStorage.setItem("piwallet.settings.fiatCurrency", "EUR");
    localStorage.setItem(KEY_LIST_SORT, "label");
    localStorage.setItem(KEY_LIST_UNIT, "bsv");
    const rec = await addWallet(DEMO);
    await setLastScan(rec.id, {
      at: new Date().toISOString(),
      totalSats: 42_000,
      utxos: [],
      lastReceiveUsed: 0,
      lastChangeUsed: -1,
      addressesScanned: 20,
      stoppedAt: { receive: 5, change: 0 },
    });

    const file = await buildWalletBackupFile({ scope: "wallets-and-settings" });
    expect(file.settings?.fiatCurrency).toBe("EUR");
    expect(file.settings?.listSort).toBe("label");
    expect(file.settings?.listUnit).toBe("bsv");
    expect(file.wallets[0].lastScan?.totalSats).toBe(42_000);
  });

  it("does not export or restore terms acceptance", async () => {
    localStorage.setItem("piwallet.termsAcceptedVersion", "1");
    localStorage.setItem("piwallet.termsAcceptedAt", "2025-01-01T00:00:00.000Z");
    await addWallet(DEMO);

    const file = await buildWalletBackupFile({ scope: "wallets-and-settings" });
    expect(JSON.stringify(file.settings)).not.toContain("termsAccepted");

    const json = serializeWalletBackup(file);
    localStorage.clear();
    await importWalletBackup(json);
    expect(localStorage.getItem("piwallet.termsAcceptedVersion")).toBeNull();
  });

  it("ignores terms fields in legacy backups on import", async () => {
    const addedAt = new Date().toISOString();
    const json = JSON.stringify({
      format: BACKUP_FORMAT,
      version: BACKUP_VERSION,
      exportedAt: addedAt,
      wallets: [{ ...DEMO, addedAt }],
      settings: {
        listSort: "label",
        termsAcceptedVersion: 1,
        termsAcceptedAt: "2025-01-01T00:00:00.000Z",
      },
    });
    localStorage.clear();
    await importWalletBackup(json);
    expect(localStorage.getItem(KEY_LIST_SORT)).toBe("label");
    expect(localStorage.getItem("piwallet.termsAcceptedVersion")).toBeNull();
  });

  it("round-trips import on an empty store with settings restored", async () => {
    localStorage.setItem(KEY_LIST_SORT, "balance");
    await addWallet(DEMO);
    const json = serializeWalletBackup(await buildWalletBackupFile());
    await _clearAllWallets();
    localStorage.clear();
    expect(await listWallets()).toHaveLength(0);

    const result = await importWalletBackup(json);
    expect(result.imported).toBe(1);
    expect(result.settingsRestored).toBe(true);
    expect(localStorage.getItem(KEY_LIST_SORT)).toBe("balance");

    const all = await listWallets();
    expect(all).toHaveLength(1);
    expect(all[0].label).toBe(DEMO.label);
  });

  it("imports v1 backups without settings", async () => {
    const addedAt = new Date().toISOString();
    const json = JSON.stringify({
      format: BACKUP_FORMAT,
      version: 1,
      exportedAt: addedAt,
      wallets: [{ ...DEMO, addedAt }],
    });
    const result = await importWalletBackup(json);
    expect(result.imported).toBe(1);
    expect(result.settingsRestored).toBe(false);
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

  it("round-trips through PW1 bytes", async () => {
    await addWallet(DEMO);
    const { json, lines } = await buildWalletBackupPw1Lines();
    expect(lines.length).toBeGreaterThan(0);
    expect(lines[0].startsWith("PW1|")).toBe(true);

    await _clearAllWallets();
    const bytes = walletBackupToBytes(json);
    const result = await importWalletBackupBytes(bytes);
    expect(result.imported).toBe(1);
    expect(await listWallets()).toHaveLength(1);
  });

  it("encodes JSON backup as PW1 lines", async () => {
    await addWallet(DEMO);
    const json = serializeWalletBackup(await buildWalletBackupFile());
    const lines = walletBackupJsonToPw1Lines(json);
    expect(lines.every((l) => l.startsWith("PW1|"))).toBe(true);
  });

  it("replace mode clears existing wallets before import", async () => {
    await addWallet({ ...DEMO, fingerprint: "22222222", label: "local only" });
    const addedAt = new Date().toISOString();
    const backup = JSON.stringify({
      format: BACKUP_FORMAT,
      version: BACKUP_VERSION,
      exportedAt: addedAt,
      wallets: [{ ...DEMO, addedAt, label: "from backup" }],
    });

    const result = await importWalletBackup(backup, { mode: "replace" });
    expect(result.imported).toBe(1);
    const all = await listWallets();
    expect(all).toHaveLength(1);
    expect(all[0].label).toBe("from backup");
  });

  it("replace mode preserves local wallets until the whole backup validates", async () => {
    await addWallet({ ...DEMO, fingerprint: "22222222", label: "keep me" });

    await expect(importWalletBackup("{", { mode: "replace" })).rejects.toBeInstanceOf(
      WalletStoreError,
    );
    expect((await listWallets()).map((wallet) => wallet.label)).toEqual(["keep me"]);

    const addedAt = new Date().toISOString();
    const invalidFingerprint = JSON.stringify({
      format: BACKUP_FORMAT,
      version: BACKUP_VERSION,
      exportedAt: addedAt,
      wallets: [{ ...DEMO, fingerprint: "00000000", addedAt }],
    });
    await expect(
      importWalletBackup(invalidFingerprint, { mode: "replace" }),
    ).rejects.toThrow(/fingerprint mismatch/);
    expect((await listWallets()).map((wallet) => wallet.label)).toEqual(["keep me"]);
  });

  it("restores lastScan snapshot on import", async () => {
    const rec = await addWallet(DEMO);
    await setLastScan(rec.id, {
      at: "2025-06-01T12:00:00.000Z",
      totalSats: 99,
      utxos: [],
      lastReceiveUsed: 0,
      lastChangeUsed: -1,
      addressesScanned: 10,
    });
    const json = serializeWalletBackup(await buildWalletBackupFile());
    await _clearAllWallets();

    await importWalletBackup(json);
    const imported = (await listWallets())[0];
    const full = await getWallet(imported.id);
    expect(full?.lastScan?.totalSats).toBe(99);
  });

  it("rejects backups from a newer companion version", async () => {
    const addedAt = new Date().toISOString();
    const json = JSON.stringify({
      format: BACKUP_FORMAT,
      version: BACKUP_VERSION + 1,
      exportedAt: addedAt,
      wallets: [{ ...DEMO, addedAt }],
    });
    await expect(importWalletBackup(json)).rejects.toThrow(BACKUP_NEWER_THAN_APP_MSG);
  });

  it("imports v1 backup without optional wallet fields", async () => {
    const addedAt = new Date().toISOString();
    const json = JSON.stringify({
      format: BACKUP_FORMAT,
      version: 1,
      exportedAt: addedAt,
      wallets: [{
        label: DEMO.label,
        xpub: DEMO.xpub,
        fingerprint: DEMO.fingerprint,
        path: DEMO.path,
        addedAt,
      }],
    });
    const result = await importWalletBackup(json);
    expect(result.imported).toBe(1);
    const w = (await listWallets())[0];
    expect(w.network ?? "main").toBe("main");
    expect(w.nextReceiveIndex ?? 0).toBe(0);
  });

  it("formats import results for display", () => {
    expect(
      formatImportWalletResult({
        imported: 2,
        skippedDuplicates: 1,
        failed: [],
        settingsRestored: true,
      }),
    ).toBe("imported 2 wallets; skipped 1 duplicate; restored settings.");
  });
});

describe("companion settings export", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("round-trips list sort via apply", () => {
    applyCompanionSettings({ listSort: "label-desc", listUnit: "fiat" });
    expect(exportCompanionSettings()).toMatchObject({
      listSort: "label-desc",
      listUnit: "fiat",
    });
  });
});

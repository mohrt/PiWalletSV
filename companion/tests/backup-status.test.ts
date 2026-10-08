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
const g = globalThis as unknown as { localStorage: Storage; sessionStorage: Storage };
g.localStorage = new MemoryStorage() as unknown as Storage;
g.sessionStorage = new MemoryStorage() as unknown as Storage;

import {
  BACKUP_SNOOZE_MS,
  type SnapshotWalletInput,
  backupSnapshot,
  backupStatus,
  isBackupNudgeSnoozed,
  markBackedUp,
  snoozeBackupNudge,
} from "../src/lib/backup-status.js";

const A: SnapshotWalletInput = {
  fingerprint: "cf987d8c",
  path: "m/44'/236'/0'",
  network: "main",
  label: "Savings",
};
const B: SnapshotWalletInput = {
  fingerprint: "0badf00d",
  path: "m/44'/236'/0'",
  network: "main",
  label: "Daily",
};

describe("backup status", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("is 'none' until a backup is recorded", () => {
    expect(backupStatus(backupSnapshot([A], {})).state).toBe("none");
  });

  it("is current right after a backup and ignores wallet order", () => {
    markBackedUp(backupSnapshot([A, B], {}), "wallets-and-settings");
    const status = backupStatus(backupSnapshot([B, A], {}));
    expect(status.state).toBe("current");
    expect(status.lastAt).not.toBeNull();
  });

  it("summarizes added, removed, renamed, and updated wallets", () => {
    markBackedUp(backupSnapshot([A, B], {}), "wallets-and-settings");
    const C = { ...A, fingerprint: "12345678", label: "New" };
    const status = backupStatus(
      backupSnapshot([{ ...A, label: "Savings 2", gapLimit: 50 }, C], {}),
    );
    expect(status.state).toBe("stale");
    expect(status.changes).toEqual([
      "1 new wallet",
      "1 wallet removed",
      "1 wallet renamed",
      "1 wallet updated",
    ]);
  });

  it("flags passkey and settings changes", () => {
    markBackedUp(backupSnapshot([A], { fiatCurrency: "USD" }), "wallets-and-settings");
    const withKey = { ...A, passkeys: [{ credentialId: "c1", name: "Pay" }] };
    expect(backupStatus(backupSnapshot([withKey], { fiatCurrency: "EUR" })).changes)
      .toEqual(["passkeys changed", "settings changed"]);
  });

  it("ignores volatile data and view preferences", () => {
    markBackedUp(backupSnapshot([A], {}), "wallets-and-settings");
    const settings = {
      listSort: "label" as const,
      listUnit: "fiat" as const,
      addressBook: [],
    };
    const noisy = { ...A, nextReceiveIndex: 7, lastScan: { totalSats: 1 } };
    expect(backupStatus(backupSnapshot([noisy], settings)).state).toBe("current");
  });

  it("ignores address book lastUsedAt but notices new entries", () => {
    const entry = { address: "1abc", label: "Shop", network: "main" as const, lastUsedAt: "2026-01-01T00:00:00Z" };
    markBackedUp(backupSnapshot([A], { addressBook: [entry] }), "wallets-and-settings");
    const bumped = { ...entry, lastUsedAt: "2026-10-01T00:00:00Z" };
    expect(backupStatus(backupSnapshot([A], { addressBook: [bumped] })).state).toBe("current");
    const added = { ...entry, address: "1def" };
    expect(backupStatus(backupSnapshot([A], { addressBook: [bumped, added] })).changes)
      .toEqual(["settings changed"]);
  });

  it("keeps settings stale after a wallets-only backup", () => {
    markBackedUp(backupSnapshot([A], { theme: "light" }), "wallets-only");
    expect(backupStatus(backupSnapshot([A], { theme: "light" })).changes)
      .toEqual(["settings changed"]);
    expect(backupStatus(backupSnapshot([A], {})).state).toBe("current");
  });

  it("snoozes only until the next change", () => {
    const snap = backupSnapshot([A], {});
    snoozeBackupNudge(snap);
    expect(isBackupNudgeSnoozed(snap)).toBe(true);
    expect(isBackupNudgeSnoozed(backupSnapshot([A, B], {}))).toBe(false);
  });

  it("snooze expires after 24 hours", () => {
    const snap = backupSnapshot([A], {});
    const t0 = Date.parse("2026-10-08T12:00:00Z");
    snoozeBackupNudge(snap, t0);
    expect(isBackupNudgeSnoozed(snap, t0 + BACKUP_SNOOZE_MS - 1)).toBe(true);
    expect(isBackupNudgeSnoozed(snap, t0 + BACKUP_SNOOZE_MS)).toBe(false);
  });
});

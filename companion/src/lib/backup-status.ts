/**
 * Tracks whether this device's wallets and settings changed since the last
 * saved backup file, so the wallets page can nudge until a backup matches.
 *
 * Per-device state in localStorage; never part of the backup file. Holds
 * wallet keys, labels, and settings (already stored locally), not xpubs.
 * Volatile data — cached scans/history, receive index, passkey lastUsedAt,
 * list sort/unit — is excluded so routine use doesn't trigger the nudge.
 */
import type { CompanionSettingsBackup } from "./companion-settings.js";
import { detectInstallPlatform, isAndroid } from "./pwa-install.js";

export const KEY_LAST_BACKUP = "piwallet.backup.lastExport";
export const KEY_BACKUP_LATER = "piwallet.backup.later";
/** sessionStorage: "export" | "import" — Settings opens that backup fold on mount. */
export const KEY_OPEN_BACKUP = "piwallet.settings.openBackup";

export type BackupScope = "wallets-only" | "wallets-and-settings";

/** Structural subset shared by WalletRecord and WalletBackupEntry. */
export interface SnapshotWalletInput {
  fingerprint: string;
  path: string;
  network?: string;
  label: string;
  gapLimit?: number;
  passkeys?: readonly { credentialId: string; name: string }[];
}

interface WalletSnapshot {
  key: string;
  label: string;
  gapLimit: number | null;
  passkeys: string[];
}

export interface BackupSnapshot {
  wallets: WalletSnapshot[];
  /** Canonical JSON of the backed-up settings subset. */
  settings: string;
}

interface StoredBackup {
  at: string;
  wallets: WalletSnapshot[];
  settings: string | null;
}

export type BackupState = "none" | "stale" | "current";

export interface BackupStatus {
  state: BackupState;
  lastAt: string | null;
  /** Human-readable change list, e.g. ["1 new wallet", "settings changed"]. */
  changes: string[];
}

function storage(): Storage | null {
  try {
    return typeof localStorage !== "undefined" ? localStorage : null;
  } catch {
    return null;
  }
}

function canonicalSettings(settings: CompanionSettingsBackup | undefined): string {
  const s = settings ?? {};
  const book = (s.addressBook ?? [])
    .map((e) => `${e.network}:${e.address}:${e.label}`)
    .sort();
  return JSON.stringify({
    defaultFeeTier: s.defaultFeeTier ?? null,
    customFeeRate: s.customFeeRate ?? null,
    fiatCurrency: s.fiatCurrency ?? null,
    defaultNetwork: s.defaultNetwork ?? null,
    theme: s.theme ?? null,
    addressBook: book,
  });
}

const EMPTY_SETTINGS = canonicalSettings(undefined);

export function backupSnapshot(
  wallets: readonly SnapshotWalletInput[],
  settings: CompanionSettingsBackup | undefined,
): BackupSnapshot {
  const snaps = wallets.map((w) => ({
    key: `${String(w.fingerprint).toLowerCase()}:${w.path}:${w.network ?? "main"}`,
    label: String(w.label ?? "").trim(),
    gapLimit: typeof w.gapLimit === "number" ? w.gapLimit : null,
    passkeys: (Array.isArray(w.passkeys) ? w.passkeys : [])
      .map((p) => `${p.credentialId}:${p.name}`)
      .sort(),
  }));
  snaps.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
  return { wallets: snaps, settings: canonicalSettings(settings) };
}

export function snapshotKey(snapshot: BackupSnapshot): string {
  return JSON.stringify(snapshot);
}

function readStored(): StoredBackup | null {
  const raw = storage()?.getItem(KEY_LAST_BACKUP);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<StoredBackup>;
    if (typeof parsed.at !== "string" || !Array.isArray(parsed.wallets)) return null;
    return {
      at: parsed.at,
      wallets: parsed.wallets,
      settings: typeof parsed.settings === "string" ? parsed.settings : null,
    };
  } catch {
    return null;
  }
}

/** Record a completed backup file. Wallets-only keeps the previous settings baseline. */
export function markBackedUp(
  snapshot: BackupSnapshot,
  scope: BackupScope,
  at: Date = new Date(),
): void {
  const prev = readStored();
  const stored: StoredBackup = {
    at: at.toISOString(),
    wallets: snapshot.wallets,
    settings: scope === "wallets-and-settings" ? snapshot.settings : prev?.settings ?? null,
  };
  storage()?.setItem(KEY_LAST_BACKUP, JSON.stringify(stored));
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function backupStatus(current: BackupSnapshot): BackupStatus {
  const stored = readStored();
  if (!stored) return { state: "none", lastAt: null, changes: [] };

  const before = new Map(stored.wallets.map((w) => [w.key, w]));
  const now = new Map(current.wallets.map((w) => [w.key, w]));
  let added = 0;
  let removed = 0;
  let renamed = 0;
  let updated = 0;
  let passkeysChanged = false;
  for (const [key, w] of now) {
    const old = before.get(key);
    if (!old) { added += 1; continue; }
    if (old.label !== w.label) renamed += 1;
    if (old.gapLimit !== w.gapLimit) updated += 1;
    if (old.passkeys.join("\n") !== w.passkeys.join("\n")) passkeysChanged = true;
  }
  for (const key of before.keys()) {
    if (!now.has(key)) removed += 1;
  }

  const changes: string[] = [];
  if (added) changes.push(plural(added, "new wallet", "new wallets"));
  if (removed) changes.push(plural(removed, "wallet removed", "wallets removed"));
  if (renamed) changes.push(plural(renamed, "wallet renamed", "wallets renamed"));
  if (updated) changes.push(plural(updated, "wallet updated", "wallets updated"));
  if (passkeysChanged) changes.push("passkeys changed");
  if (current.settings !== (stored.settings ?? EMPTY_SETTINGS)) changes.push("settings changed");

  return {
    state: changes.length ? "stale" : "current",
    lastAt: stored.at,
    changes,
  };
}

/** iOS can keep a Home Screen app's session alive for days; cap "Later". */
export const BACKUP_SNOOZE_MS = 24 * 60 * 60 * 1000;

/** "Later" hides the nudge until the next change, next launch, or 24 hours. */
export function isBackupNudgeSnoozed(current: BackupSnapshot, now: number = Date.now()): boolean {
  try {
    const raw = sessionStorage.getItem(KEY_BACKUP_LATER);
    if (!raw) return false;
    const snooze = JSON.parse(raw) as { key?: unknown; until?: unknown };
    return (
      snooze.key === snapshotKey(current) &&
      typeof snooze.until === "number" &&
      now < snooze.until
    );
  } catch {
    return false;
  }
}

export function snoozeBackupNudge(current: BackupSnapshot, now: number = Date.now()): void {
  try {
    sessionStorage.setItem(
      KEY_BACKUP_LATER,
      JSON.stringify({ key: snapshotKey(current), until: now + BACKUP_SNOOZE_MS }),
    );
  } catch { /* private mode: nudge just stays visible */ }
}

export type BackupPlatform = "ios" | "android" | "desktop";

export function backupPlatform(): BackupPlatform {
  if (detectInstallPlatform() === "ios") return "ios";
  if (isAndroid()) return "android";
  return "desktop";
}

export function backupSaveCopy(platform: BackupPlatform): { label: string; hint: string } {
  switch (platform) {
    case "ios":
      return {
        label: "Save to Files",
        hint: "Choose Save to Files → iCloud Drive → a PiWalletSV folder, so the backup survives losing this phone.",
      };
    case "android":
      return {
        label: "Save backup",
        hint: "Save to Google Drive (a PiWalletSV folder) or Downloads.",
      };
    default:
      return {
        label: "Download backup",
        hint: "Keep a copy somewhere other than this browser.",
      };
  }
}

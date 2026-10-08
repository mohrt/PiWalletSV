/**
 * Save a backup file (share sheet on phones, download on desktop) and
 * describe a chosen backup before restoring it.
 */
import {
  type BackupPlatform,
  type BackupScope,
  type BackupSnapshot,
  backupSnapshot,
  markBackedUp,
} from "../lib/backup-status.js";
import {
  BACKUP_NEWER_THAN_APP_MSG,
  type WalletBackupSummary,
  backupFileName,
  buildWalletBackupFile,
  serializeWalletBackup,
} from "../lib/wallet-backup.js";

export type SaveOutcome = "shared" | "downloaded" | "cancelled";

export interface SavedBackup {
  outcome: SaveOutcome;
  walletCount: number;
  scope: BackupScope;
}

function downloadFile(file: File): void {
  const url = URL.createObjectURL(file);
  const a = document.createElement("a");
  a.href = url;
  a.download = file.name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function deliverFile(file: File, platform: BackupPlatform): Promise<SaveOutcome> {
  const canShareFile =
    platform !== "desktop" &&
    typeof navigator.canShare === "function" &&
    navigator.canShare({ files: [file] });
  if (canShareFile) {
    try {
      await navigator.share({ files: [file], title: "PiWalletSV backup" });
      return "shared";
    } catch (e) {
      if ((e as Error).name === "AbortError") return "cancelled";
      // NotAllowedError (lost user activation) and friends: fall back to download.
    }
  }
  downloadFile(file);
  return "downloaded";
}

/**
 * Build a fresh backup, hand it to the platform, and record it as the
 * latest backup unless the user cancelled. Call from a click handler.
 */
export async function saveBackup(
  platform: BackupPlatform,
  scope: BackupScope = "wallets-and-settings",
): Promise<SavedBackup> {
  const now = new Date();
  const backup = await buildWalletBackupFile({ scope });
  const file = new File(
    [serializeWalletBackup(backup)],
    backupFileName(now, backup.wallets.length),
    { type: "application/json" },
  );
  const outcome = await deliverFile(file, platform);
  if (outcome !== "cancelled") {
    markBackedUp(backupSnapshot(backup.wallets, backup.settings), scope, now);
  }
  return { outcome, walletCount: backup.wallets.length, scope };
}

export function savedBackupMessage(saved: SavedBackup): string {
  const n = saved.walletCount;
  const what = `${n} wallet${n === 1 ? "" : "s"}` +
    (saved.scope === "wallets-and-settings" ? " and settings" : "");
  return saved.outcome === "shared"
    ? `Backup saved (${what}).`
    : `Backup downloaded (${what}).`;
}

/** Mark a restored backup file as the current baseline. */
export function markRestoredFromFile(summary: WalletBackupSummary): void {
  const snapshot: BackupSnapshot = backupSnapshot(
    summary.file.wallets,
    summary.file.settings,
  );
  markBackedUp(snapshot, summary.hasSettings ? "wallets-and-settings" : "wallets-only");
}

/** "Backup from Oct 8, 2026, 12:05 PM: 3 wallets (Savings, Daily, Test)". */
export function describeBackup(summary: WalletBackupSummary): string {
  const when = Date.parse(summary.exportedAt);
  const date = Number.isNaN(when)
    ? "an unknown date"
    : new Date(when).toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      });
  const n = summary.walletCount;
  const shown = summary.labels.slice(0, 3);
  const more = summary.labels.length - shown.length;
  const names = shown.length
    ? ` (${shown.join(", ")}${more > 0 ? `, +${more} more` : ""})`
    : "";
  return `Backup from ${date}: ${n} wallet${n === 1 ? "" : "s"}${names}.`;
}

export function notABackupMessage(e: unknown): string {
  const msg = e instanceof Error ? e.message : String(e);
  return msg === BACKUP_NEWER_THAN_APP_MSG
    ? msg
    : "This isn't a PiWalletSV backup file.";
}

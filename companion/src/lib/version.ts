/**
 * Companion app version and backup-format derivation.
 *
 * `APP_VERSION` is injected from package.json at build time (see vite.config.ts).
 * Backup JSON `version` is an integer schema tag derived from that semver so we
 * do not maintain a separate backup-version constant.
 */

/** Companion semver from package.json (Vite `define`). */
export const APP_VERSION: string =
  import.meta.env.VITE_APP_VERSION ?? "0.1.0-a0";

/**
 * Map companion semver to backup JSON `version` integer.
 *
 * Pre-1.0: 0.0.x → 1 (wallets only), 0.1+ → 2 (+ settings / cached snapshots).
 * Post-1.0: major * 100 + minor — room for schema bumps per release line.
 */
export function backupFormatVersion(
  companionVersion: string = APP_VERSION,
): number {
  const m = companionVersion.trim().match(/^(\d+)\.(\d+)/);
  if (!m) return 1;
  const major = Number(m[1]);
  const minor = Number(m[2]);
  if (major === 0) {
    return minor >= 1 ? 2 : 1;
  }
  return major * 100 + minor;
}

/** Highest backup format integer this companion build can import. */
export const BACKUP_FORMAT_VERSION = backupFormatVersion();

/** @deprecated Use {@link BACKUP_FORMAT_VERSION}; kept for existing imports. */
export const BACKUP_VERSION = BACKUP_FORMAT_VERSION;

/** Display label, e.g. `v0.1.0-a0`. */
export function formatAppVersion(version: string = APP_VERSION): string {
  return version.startsWith("v") ? version : `v${version}`;
}

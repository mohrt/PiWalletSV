/**
 * First-load disclaimer state machine.
 *
 * The companion PWA must surface `DISCLAIMER.md` to the user on their
 * first visit and again whenever the disclaimer's `termsVersion` is
 * bumped (because the document materially changed). Acceptance is
 * persisted to `localStorage` so we don't nag every page-load.
 *
 * Storage keys (string values, namespaced to avoid collisions):
 *   piwallet.termsAcceptedVersion : numeric, last accepted version
 *   piwallet.termsAcceptedAt      : ISO 8601 timestamp
 *
 * Note: localStorage is browser-tab-isolated. The Pi side has its own
 * acknowledgment flow tracked in the vault metadata (see the
 * pi-first-boot-tos todo).
 */

export const CURRENT_TERMS_VERSION = 2;

const KEY_VERSION = "piwallet.termsAcceptedVersion";
const KEY_AT = "piwallet.termsAcceptedAt";

export interface AcceptanceInfo {
  acceptedVersion: number;
  acceptedAt: string;
}

function getStorage(): Storage | null {
  try {
    return typeof localStorage !== "undefined" ? localStorage : null;
  } catch {
    // SecurityError when localStorage is disabled by site settings.
    return null;
  }
}

export function getAcceptance(): AcceptanceInfo | null {
  const store = getStorage();
  if (!store) return null;
  const rawV = store.getItem(KEY_VERSION);
  const rawA = store.getItem(KEY_AT);
  if (rawV === null || rawA === null) return null;
  const v = Number.parseInt(rawV, 10);
  if (!Number.isFinite(v)) return null;
  return { acceptedVersion: v, acceptedAt: rawA };
}

/** True when the user has already accepted at the current version. */
export function isTermsAccepted(): boolean {
  const info = getAcceptance();
  return info !== null && info.acceptedVersion >= CURRENT_TERMS_VERSION;
}

/** Persist a fresh acceptance at `CURRENT_TERMS_VERSION`. */
export function recordAcceptance(): AcceptanceInfo {
  const store = getStorage();
  const info: AcceptanceInfo = {
    acceptedVersion: CURRENT_TERMS_VERSION,
    acceptedAt: new Date().toISOString(),
  };
  if (store) {
    store.setItem(KEY_VERSION, String(info.acceptedVersion));
    store.setItem(KEY_AT, info.acceptedAt);
  }
  return info;
}

/** Test / dev helper — wipe the persisted acceptance. */
export function clearAcceptance(): void {
  const store = getStorage();
  if (!store) return;
  store.removeItem(KEY_VERSION);
  store.removeItem(KEY_AT);
}

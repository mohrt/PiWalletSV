/**
 * Local ring buffer of WoC fee recommendations for trend display.
 *
 * WoC has no historical fee API; we sample on each successful fetch and
 * keep the last {@link MAX_FEE_HISTORY} snapshots in localStorage.
 */
import type { FeeRecommendation } from "./fee.js";

export interface FeeSnapshot {
  at: string;
  economy: number;
  standard: number;
  priority: number;
  fromApi: boolean;
}

export const KEY_FEE_HISTORY = "piwallet.feeHistory";
export const MAX_FEE_HISTORY = 48;

/** Skip a new row if the last sample is within this window. */
const DEDUPE_MS = 5 * 60_000;

function storage(): Storage | null {
  try {
    return typeof localStorage !== "undefined" ? localStorage : null;
  } catch {
    return null;
  }
}

function readRaw(): FeeSnapshot[] {
  const store = storage();
  if (!store) return [];
  try {
    const parsed = JSON.parse(store.getItem(KEY_FEE_HISTORY) ?? "[]") as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isValidSnapshot);
  } catch {
    return [];
  }
}

function writeRaw(snapshots: FeeSnapshot[]): void {
  storage()?.setItem(KEY_FEE_HISTORY, JSON.stringify(snapshots.slice(-MAX_FEE_HISTORY)));
}

function isValidSnapshot(raw: unknown): raw is FeeSnapshot {
  if (typeof raw !== "object" || raw === null) return false;
  const s = raw as Record<string, unknown>;
  return (
    typeof s.at === "string" &&
    typeof s.economy === "number" &&
    typeof s.standard === "number" &&
    typeof s.priority === "number" &&
    typeof s.fromApi === "boolean"
  );
}

export function getFeeHistory(): FeeSnapshot[] {
  return readRaw();
}

/** Append or refresh the latest row after a fee fetch. */
export function recordFeeSnapshot(rec: FeeRecommendation): void {
  const snap: FeeSnapshot = {
    at: rec.fetchedAt,
    economy: rec.economy,
    standard: rec.standard,
    priority: rec.priority,
    fromApi: rec.fromApi,
  };
  const history = readRaw();
  const last = history[history.length - 1];
  if (last) {
    const lastMs = Date.parse(last.at);
    const snapMs = Date.parse(snap.at);
    if (
      Number.isFinite(lastMs) &&
      Number.isFinite(snapMs) &&
      snapMs - lastMs < DEDUPE_MS
    ) {
      history[history.length - 1] = snap;
      writeRaw(history);
      return;
    }
  }
  writeRaw([...history, snap]);
}

export function clearFeeHistory(): void {
  storage()?.removeItem(KEY_FEE_HISTORY);
}

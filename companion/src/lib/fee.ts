/**
 * Fee rate recommendation helper.
 *
 * Uses WoC's `GET /feerecommendation` endpoint, which returns the current
 * recommended fee in sat/kB. From that we derive three tiers:
 *
 *   Economy  = max(50,  standard * 0.5)   — safe for non-urgent txs
 *   Standard = WoC recommendation         — confirmed within a few blocks
 *   Priority = standard * 5               — fast confirmation
 *
 * BSV block times are ~10 min and the mempool is usually thin, so
 * Economy and Standard are nearly always sufficient. The WoC recommended
 * value is typically 100 sat/kB; we use that as a hard fallback so the
 * UI always has a sensible default even if the API call fails.
 *
 * The result is cached in-memory for 60 s so opening the send flow
 * multiple times doesn't spam the API.
 */

import type { WocClient } from "./woc.js";

/** BSV network recommended fee in sat/kB as of 2025. */
export const DEFAULT_FEE_RATE_SATSKB = 100;

export interface FeeRecommendation {
  /** sat/kB — lowest safe rate */
  economy: number;
  /** sat/kB — WoC recommended, normally confirmed in the next block */
  standard: number;
  /** sat/kB — fastest confirmation */
  priority: number;
  /** ISO 8601 timestamp the rates were last fetched from WoC. */
  fetchedAt: string;
  /** true if the rates came from the API; false if using fallback defaults. */
  fromApi: boolean;
}

/** Raw shape from WoC `GET /feerecommendation`. */
interface WocFeeRec {
  fee?: number;
  fee_unit?: string;
  mempool_min_fee?: number;
}

let _cache: FeeRecommendation | null = null;
let _cacheAt = 0;
const CACHE_TTL_MS = 60_000;

/** Clear the in-memory cache (for tests). */
export function _resetFeeCache(): void {
  _cache = null;
  _cacheAt = 0;
}

function buildRec(standard: number, fromApi: boolean): FeeRecommendation {
  return {
    economy: Math.max(50, Math.round(standard * 0.5)),
    standard,
    priority: standard * 5,
    fetchedAt: new Date().toISOString(),
    fromApi,
  };
}

/**
 * Fetch the current fee recommendation from WoC's `/feerecommendation`
 * endpoint. Falls back to {@link DEFAULT_FEE_RATE_SATSKB} if the request
 * fails or returns a non-positive value.
 *
 * Results are cached for 60 s to avoid hitting the API on every send.
 */
export async function fetchFeeRecommendation(
  woc: WocClient,
): Promise<FeeRecommendation> {
  const now = Date.now();
  if (_cache && now - _cacheAt < CACHE_TTL_MS) return _cache;

  let rec: FeeRecommendation;
  try {
    const url = `${woc.baseUrl}/feerecommendation`;
    const resp = await fetch(url, {
      headers: { Accept: "application/json" },
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = (await resp.json()) as WocFeeRec;
    const fee = typeof data?.fee === "number" && data.fee > 0
      ? data.fee
      : DEFAULT_FEE_RATE_SATSKB;
    rec = buildRec(fee, true);
  } catch {
    // Network error, non-JSON, or API returned bad data — use default.
    rec = buildRec(DEFAULT_FEE_RATE_SATSKB, false);
  }

  _cache = rec;
  _cacheAt = now;
  return rec;
}

/** Format a sat/kB fee rate for display (e.g. "100 sat/kB"). */
export function formatFeeRate(satskb: number): string {
  return `${satskb.toLocaleString("en-US")} sat/kB`;
}

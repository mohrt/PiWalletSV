import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { _resetFeeCache, fetchFeeRecommendation } from "../src/lib/fee.js";
import { getFeeHistory, recordFeeSnapshot } from "../src/lib/fee-history.js";
import { WocClient } from "../src/lib/woc.js";

class MemoryStorage {
  private map = new Map<string, string>();
  get length(): number { return this.map.size; }
  clear(): void { this.map.clear(); }
  getItem(k: string): string | null { return this.map.get(k) ?? null; }
  setItem(k: string, v: string): void { this.map.set(k, String(v)); }
  removeItem(k: string): void { this.map.delete(k); }
  key(i: number): string | null { return Array.from(this.map.keys())[i] ?? null; }
}

describe("fee-history", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", new MemoryStorage());
  });

  afterEach(() => {
    _resetFeeCache();
    vi.unstubAllGlobals();
  });

  it("records snapshots from fee recommendation", () => {
    recordFeeSnapshot({
      economy: 50,
      standard: 100,
      priority: 500,
      fetchedAt: "2025-01-01T00:00:00.000Z",
      fromApi: true,
    });
    expect(getFeeHistory()).toHaveLength(1);
    expect(getFeeHistory()[0].standard).toBe(100);
  });

  it("dedupes samples within five minutes", () => {
    recordFeeSnapshot({
      economy: 50,
      standard: 100,
      priority: 500,
      fetchedAt: "2025-01-01T00:00:00.000Z",
      fromApi: true,
    });
    recordFeeSnapshot({
      economy: 50,
      standard: 120,
      priority: 600,
      fetchedAt: "2025-01-01T00:02:00.000Z",
      fromApi: true,
    });
    const history = getFeeHistory();
    expect(history).toHaveLength(1);
    expect(history[0].standard).toBe(120);
  });

  it("fetchFeeRecommendation appends to history", async () => {
    const woc = new WocClient({ baseUrl: "https://example.test" });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ fee: 100 }),
      }),
    );
    await fetchFeeRecommendation(woc);
    expect(getFeeHistory().length).toBeGreaterThan(0);
  });
});

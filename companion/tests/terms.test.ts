import { beforeEach, describe, expect, it } from "vitest";

// Minimal localStorage shim for the Node vitest environment.
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
  CURRENT_TERMS_VERSION,
  clearAcceptance,
  getAcceptance,
  isTermsAccepted,
  recordAcceptance,
} from "../src/lib/terms.js";

describe("terms state machine", () => {
  beforeEach(() => {
    clearAcceptance();
  });

  it("reports not-accepted on a fresh storage", () => {
    expect(isTermsAccepted()).toBe(false);
    expect(getAcceptance()).toBeNull();
  });

  it("recordAcceptance persists the current version + ISO timestamp", () => {
    const info = recordAcceptance();
    expect(info.acceptedVersion).toBe(CURRENT_TERMS_VERSION);
    expect(info.acceptedAt).toMatch(
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/,
    );
    expect(isTermsAccepted()).toBe(true);
  });

  it("older-version acceptance does not satisfy the current requirement", () => {
    // Simulate a stale acceptance from a previous version.
    localStorage.setItem(
      "piwallet.termsAcceptedVersion",
      String(CURRENT_TERMS_VERSION - 1),
    );
    localStorage.setItem(
      "piwallet.termsAcceptedAt",
      "2026-01-01T00:00:00.000Z",
    );
    expect(isTermsAccepted()).toBe(false);
    const info = getAcceptance();
    expect(info?.acceptedVersion).toBe(CURRENT_TERMS_VERSION - 1);
  });

  it("clearAcceptance wipes both keys", () => {
    recordAcceptance();
    expect(isTermsAccepted()).toBe(true);
    clearAcceptance();
    expect(isTermsAccepted()).toBe(false);
    expect(getAcceptance()).toBeNull();
  });

  it("ignores malformed stored version", () => {
    localStorage.setItem("piwallet.termsAcceptedVersion", "not-a-number");
    localStorage.setItem(
      "piwallet.termsAcceptedAt",
      "2026-05-11T00:00:00.000Z",
    );
    expect(getAcceptance()).toBeNull();
    expect(isTermsAccepted()).toBe(false);
  });
});

import { describe, expect, it, vi, afterEach } from "vitest";

import { relativeTimeFrom } from "../src/lib/relative-time.js";

describe("relativeTimeFrom", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns seconds ago for recent timestamps", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-27T12:00:30Z"));
    expect(relativeTimeFrom("2026-05-27T12:00:00Z")).toBe("30s ago");
  });

  it("returns minutes ago", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-27T12:05:00Z"));
    expect(relativeTimeFrom("2026-05-27T12:00:00Z")).toBe("5m ago");
  });
});

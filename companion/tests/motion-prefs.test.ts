import { afterEach, describe, expect, it, vi } from "vitest";

import {
  onReducedMotionChange,
  prefersReducedMotion,
} from "../src/lib/motion-prefs.js";

function mockMatchMedia(initial: boolean) {
  const listeners = new Set<(ev: MediaQueryListEvent) => void>();
  const mq = {
    matches: initial,
    media: "(prefers-reduced-motion: reduce)",
    addEventListener: (_: string, fn: (ev: MediaQueryListEvent) => void) => {
      listeners.add(fn);
    },
    removeEventListener: (_: string, fn: (ev: MediaQueryListEvent) => void) => {
      listeners.delete(fn);
    },
    dispatch(next: boolean) {
      mq.matches = next;
      for (const fn of listeners) {
        fn({ matches: next } as MediaQueryListEvent);
      }
    },
  };

  vi.stubGlobal("window", {
    matchMedia: (query: string) => {
      expect(query).toBe("(prefers-reduced-motion: reduce)");
      return mq;
    },
  });

  return mq;
}

describe("motion-prefs", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns false when matchMedia is unavailable", () => {
    vi.stubGlobal("window", {});
    expect(prefersReducedMotion()).toBe(false);
  });

  it("reads prefers-reduced-motion from matchMedia", () => {
    mockMatchMedia(true);
    expect(prefersReducedMotion()).toBe(true);
    mockMatchMedia(false);
    expect(prefersReducedMotion()).toBe(false);
  });

  it("notifies listeners when the preference changes", () => {
    const mq = mockMatchMedia(false);
    const seen: boolean[] = [];
    const off = onReducedMotionChange((v) => seen.push(v));
    mq.dispatch(true);
    mq.dispatch(false);
    off();
    expect(seen).toEqual([true, false]);
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  KEY_INSTALL_DISMISSED,
  _resetInstallPromptForTests,
  dismissInstallPrompt,
  isInstallPromptDismissed,
  isStandalonePwa,
  shouldShowInstallBanner,
} from "../src/lib/pwa-install.js";

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

function mockWindow(opts: {
  standalone?: boolean;
  displayStandalone?: boolean;
  minWidth768?: boolean;
}): void {
  vi.stubGlobal("window", {
    matchMedia: (query: string) => ({
      matches:
        query === "(display-mode: standalone)"
          ? (opts.displayStandalone ?? false)
          : query === "(min-width: 768px)"
            ? (opts.minWidth768 ?? false)
            : false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  });
  vi.stubGlobal("navigator", {
    standalone: opts.standalone ?? false,
    userAgent: "Mozilla/5.0",
    platform: "iPhone",
    maxTouchPoints: 1,
  });
}

describe("pwa-install", () => {
  beforeEach(() => {
    (globalThis as unknown as { localStorage: Storage }).localStorage =
      new MemoryStorage() as unknown as Storage;
    _resetInstallPromptForTests();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("detects standalone via display-mode", () => {
    mockWindow({ displayStandalone: true });
    expect(isStandalonePwa()).toBe(true);
  });

  it("detects iOS standalone flag", () => {
    mockWindow({ standalone: true });
    expect(isStandalonePwa()).toBe(true);
  });

  it("persists dismiss in localStorage", () => {
    expect(isInstallPromptDismissed()).toBe(false);
    dismissInstallPrompt();
    expect(localStorage.getItem(KEY_INSTALL_DISMISSED)).toBe("1");
    expect(isInstallPromptDismissed()).toBe(true);
  });

  it("shouldShowInstallBanner is false when standalone", () => {
    mockWindow({ displayStandalone: true });
    expect(shouldShowInstallBanner()).toBe(false);
  });

  it("shouldShowInstallBanner is false when dismissed", () => {
    mockWindow({});
    dismissInstallPrompt();
    expect(shouldShowInstallBanner()).toBe(false);
  });

  it("shouldShowInstallBanner is false on wide desktop", () => {
    mockWindow({ minWidth768: true });
    expect(shouldShowInstallBanner()).toBe(false);
  });

  it("shouldShowInstallBanner is true on mobile browser", () => {
    mockWindow({});
    expect(shouldShowInstallBanner()).toBe(true);
  });
});

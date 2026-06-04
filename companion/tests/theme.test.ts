import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { KEY_THEME } from "../src/lib/companion-settings.js";
import { applyTheme, setThemePreference } from "../src/lib/theme.js";

class MemoryStorage {
  private map = new Map<string, string>();
  get length(): number { return this.map.size; }
  clear(): void { this.map.clear(); }
  getItem(k: string): string | null { return this.map.get(k) ?? null; }
  setItem(k: string, v: string): void { this.map.set(k, String(v)); }
  removeItem(k: string): void { this.map.delete(k); }
  key(i: number): string | null { return Array.from(this.map.keys())[i] ?? null; }
}

describe("theme", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", new MemoryStorage());
    vi.stubGlobal("document", {
      documentElement: {
        dataset: {} as DOMStringMap,
        style: {} as CSSStyleDeclaration,
      },
      querySelector: () => null,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("applies light theme to document root", () => {
    setThemePreference("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem(KEY_THEME)).toBe("light");
  });

  it("applies dark theme by default", () => {
    applyTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});

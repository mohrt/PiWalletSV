import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getAddressBook,
  getAddressBookForNetwork,
  removeAddressBookEntry,
  upsertAddressBookEntry,
} from "../src/lib/address-book.js";

class MemoryStorage {
  private map = new Map<string, string>();
  get length(): number { return this.map.size; }
  clear(): void { this.map.clear(); }
  getItem(k: string): string | null { return this.map.get(k) ?? null; }
  setItem(k: string, v: string): void { this.map.set(k, String(v)); }
  removeItem(k: string): void { this.map.delete(k); }
  key(i: number): string | null { return Array.from(this.map.keys())[i] ?? null; }
}

describe("address-book", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", new MemoryStorage());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("upserts and lists entries per network", () => {
    upsertAddressBookEntry("1Alice", "main", "Alice");
    upsertAddressBookEntry("mBob", "test", "Bob");

    expect(getAddressBookForNetwork("main")).toHaveLength(1);
    expect(getAddressBookForNetwork("test")[0].label).toBe("Bob");
    expect(getAddressBook()).toHaveLength(2);
  });

  it("bumps existing entry to front and preserves label when omitted", () => {
    upsertAddressBookEntry("1Alice", "main", "Alice");
    upsertAddressBookEntry("1Other", "main", "Other");
    upsertAddressBookEntry("1Alice", "main");

    const book = getAddressBookForNetwork("main");
    expect(book[0].address).toBe("1Alice");
    expect(book[0].label).toBe("Alice");
  });

  it("removes by address and network", () => {
    upsertAddressBookEntry("1Alice", "main");
    removeAddressBookEntry("1Alice", "main");
    expect(getAddressBook()).toHaveLength(0);
  });
});

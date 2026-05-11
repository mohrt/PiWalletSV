import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  CHANGE_BRANCH,
  DerivationError,
  RECEIVE_BRANCH,
  deriveAddress,
  deriveAddressBatch,
  encodeP2pkhAddress,
} from "../src/lib/derive.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const FIXTURE_PATH = join(__dirname, "../../tests/fixtures/addresses_canonical.json");

interface AddressEntry {
  index: number;
  address: string;
}

interface AddressFixture {
  mnemonic: string;
  path: string;
  fingerprint: string;
  xpub: string;
  addresses: {
    receive: AddressEntry[];
    change: AddressEntry[];
  };
}

const fixture = JSON.parse(readFileSync(FIXTURE_PATH, "utf8")) as AddressFixture;

describe("address derivation (TS) matches Python fixture", () => {
  it("produces the same receive addresses for indices 0..4", () => {
    for (const expected of fixture.addresses.receive) {
      const got = deriveAddress(fixture.xpub, RECEIVE_BRANCH, expected.index);
      expect(got.address).toBe(expected.address);
      expect(got.subPath).toBe(`0/${expected.index}`);
      expect(got.publicKey).toHaveLength(33); // compressed sec
      expect(got.hash160).toHaveLength(20);
    }
  });

  it("produces the same change addresses for indices 0..2", () => {
    for (const expected of fixture.addresses.change) {
      const got = deriveAddress(fixture.xpub, CHANGE_BRANCH, expected.index);
      expect(got.address).toBe(expected.address);
      expect(got.subPath).toBe(`1/${expected.index}`);
    }
  });

  it("deriveAddressBatch yields the same addresses as N single derivations", () => {
    const batch = deriveAddressBatch(fixture.xpub, RECEIVE_BRANCH, 0, 5);
    expect(batch).toHaveLength(5);
    for (let i = 0; i < 5; i++) {
      expect(batch[i].address).toBe(fixture.addresses.receive[i].address);
    }
  });
});

describe("address derivation guards", () => {
  it("rejects non-xpub strings", () => {
    expect(() => deriveAddress("not-an-xpub", 0, 0)).toThrow(DerivationError);
  });

  it("rejects branches other than 0 or 1", () => {
    expect(() => deriveAddress(fixture.xpub, 2, 0)).toThrow(/branch/);
    expect(() => deriveAddress(fixture.xpub, -1, 0)).toThrow(/branch/);
  });

  it("rejects negative or hardened index", () => {
    expect(() => deriveAddress(fixture.xpub, 0, -1)).toThrow(/index/);
    expect(() => deriveAddress(fixture.xpub, 0, 0x80000000)).toThrow(/index/);
    expect(() => deriveAddress(fixture.xpub, 0, 1.5)).toThrow(/index/);
  });

  it("encodeP2pkhAddress validates HASH160 length", () => {
    expect(() => encodeP2pkhAddress(new Uint8Array(19))).toThrow(DerivationError);
    expect(() => encodeP2pkhAddress(new Uint8Array(21))).toThrow(DerivationError);
  });

  it("deriveAddressBatch rejects out-of-range count", () => {
    expect(() => deriveAddressBatch(fixture.xpub, 0, 0, -1)).toThrow(/count/);
    expect(() => deriveAddressBatch(fixture.xpub, 0, 0, 1001)).toThrow(/count/);
  });
});

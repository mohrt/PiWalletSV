import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  BSV_P2PKH_PREFIX,
  BSV_TESTNET_P2PKH_PREFIX,
  CHANGE_BRANCH,
  DerivationError,
  RECEIVE_BRANCH,
  addressFromP2pkhLockHex,
  deriveAddress,
  deriveAddressBatch,
  encodeP2pkhAddress,
  prefixForNetwork,
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

describe("network-aware address rendering", () => {
  // Same canonical mnemonic as the Python tests; the testnet vectors
  // were captured directly from piwallet.core.derivation.derive_address
  // with network='test' to lock TS↔Python parity for both networks.
  const TESTNET_RECEIVE = [
    "mycHrh2o8UWnXM3Qk218KvMSSM8FWgNxFH",
    "mtDoCVz5ZzZfBu8jr9yzsodsWUM4Fc7Q14",
    "mjbTCux3QNo9rJ8Pc84zKJvBqG7MYWcUDa",
  ];
  const TESTNET_CHANGE = [
    "mgbDYw1XgFLEmPDrgEqtx91cmXVjPGg6un",
    "mwgxkbe9DDLNqZxGt4U8fhmYNWc1P4Wxvq",
    "mv1AEn6fcR9cHhZSv3q2gNFaHk6pZEDcyu",
  ];

  it("prefixForNetwork maps to the BSV version bytes", () => {
    expect(prefixForNetwork("main")).toBe(BSV_P2PKH_PREFIX);
    expect(prefixForNetwork("test")).toBe(BSV_TESTNET_P2PKH_PREFIX);
    expect(BSV_P2PKH_PREFIX).toBe(0x00);
    expect(BSV_TESTNET_P2PKH_PREFIX).toBe(0x6f);
  });

  it("default kwarg keeps mainnet rendering byte-for-byte", () => {
    const got = deriveAddress(fixture.xpub, RECEIVE_BRANCH, 0);
    expect(got.address).toBe(fixture.addresses.receive[0].address);
  });

  it("renders testnet receive addresses for the canonical xpub", () => {
    for (let i = 0; i < TESTNET_RECEIVE.length; i++) {
      const got = deriveAddress(fixture.xpub, RECEIVE_BRANCH, i, "test");
      expect(got.address).toBe(TESTNET_RECEIVE[i]);
    }
  });

  it("renders testnet change addresses for the canonical xpub", () => {
    for (let i = 0; i < TESTNET_CHANGE.length; i++) {
      const got = deriveAddress(fixture.xpub, CHANGE_BRANCH, i, "test");
      expect(got.address).toBe(TESTNET_CHANGE[i]);
    }
  });

  it("HASH160 + publicKey are network-invariant", () => {
    const m = deriveAddress(fixture.xpub, RECEIVE_BRANCH, 0, "main");
    const t = deriveAddress(fixture.xpub, RECEIVE_BRANCH, 0, "test");
    expect(Array.from(t.hash160)).toEqual(Array.from(m.hash160));
    expect(Array.from(t.publicKey)).toEqual(Array.from(m.publicKey));
    expect(m.address).not.toBe(t.address);
  });

  it("deriveAddressBatch threads the network through", () => {
    const batch = deriveAddressBatch(fixture.xpub, RECEIVE_BRANCH, 0, 3, "test");
    for (let i = 0; i < 3; i++) {
      expect(batch[i].address).toBe(TESTNET_RECEIVE[i]);
    }
  });

  it("addressFromP2pkhLockHex round-trips a derived address", () => {
    const got = deriveAddress(fixture.xpub, RECEIVE_BRANCH, 0, "main");
    const lockHex =
      "76a914" +
      Array.from(got.hash160)
        .map((b) => b.toString(16).padStart(2, "0"))
        .join("") +
      "88ac";
    expect(addressFromP2pkhLockHex(lockHex, "main")).toBe(got.address);
    expect(addressFromP2pkhLockHex(lockHex, "test")).not.toBe(got.address);
    expect(addressFromP2pkhLockHex("00")).toBeNull();
  });
});

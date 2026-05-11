/**
 * Watch-only address derivation from a paired wallet's account xpub.
 *
 * BSV uses the same P2PKH base58check format as Bitcoin (mainnet prefix
 * 0x00). PiWalletSV pairs at the BIP44 account level (`m/44'/236'/0'`),
 * so the companion only needs the non-hardened `change/index` legs:
 *
 *     <xpub>/<change>/<index>          # 0 = receive, 1 = change
 *
 * Implemented with audited primitives:
 * - `@scure/bip32` for BIP32 CKD,
 * - `@noble/hashes` for SHA-256 + RIPEMD-160 (HASH160),
 * - `@scure/base` for base58check.
 *
 * The Pi-side `piwallet/core/derivation.py` is the reference; the
 * `tests/fixtures/addresses_canonical.json` cross-check pins this
 * implementation against it byte-for-byte.
 */
import { HDKey } from "@scure/bip32";
import { base58check } from "@scure/base";
import { ripemd160 } from "@noble/hashes/legacy.js";
import { sha256 } from "@noble/hashes/sha2.js";

export const RECEIVE_BRANCH = 0;
export const CHANGE_BRANCH = 1;
export const BSV_P2PKH_PREFIX = 0x00; // mainnet legacy address byte

const BIP32_HARDENED_THRESHOLD = 0x80000000;

const b58 = base58check(sha256);

export class DerivationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DerivationError";
  }
}

export interface DerivedAddress {
  /** Branch index — 0 (receive) or 1 (change). */
  change: number;
  /** Leaf index inside the branch. */
  index: number;
  /** Full BIP32 sub-path appended to the account xpub. */
  subPath: string;
  /** Compressed secp256k1 public key (33 bytes). */
  publicKey: Uint8Array;
  /** HASH160(publicKey) — 20 bytes. */
  hash160: Uint8Array;
  /** Base58Check-encoded P2PKH address (mainnet prefix). */
  address: string;
}

function hash160(pub: Uint8Array): Uint8Array {
  return ripemd160(sha256(pub));
}

/** Encode a 20-byte HASH160 as a P2PKH base58check address. */
export function encodeP2pkhAddress(
  h160: Uint8Array,
  prefix: number = BSV_P2PKH_PREFIX,
): string {
  if (h160.byteLength !== 20) {
    throw new DerivationError(`hash160 must be 20 bytes, got ${h160.byteLength}`);
  }
  const versioned = new Uint8Array(21);
  versioned[0] = prefix & 0xff;
  versioned.set(h160, 1);
  return b58.encode(versioned);
}

function assertNonHardened(branch: number, index: number): void {
  if (branch !== RECEIVE_BRANCH && branch !== CHANGE_BRANCH) {
    throw new DerivationError(
      `branch must be 0 (receive) or 1 (change), got ${branch}`,
    );
  }
  if (!Number.isInteger(index) || index < 0 || index >= BIP32_HARDENED_THRESHOLD) {
    throw new DerivationError(`index out of non-hardened range: ${index}`);
  }
}

/**
 * Derive a single P2PKH address from the account xpub at
 * `<xpub>/change/index`.
 */
export function deriveAddress(
  accountXpub: string,
  change: number,
  index: number,
): DerivedAddress {
  assertNonHardened(change, index);
  let parent: HDKey;
  try {
    parent = HDKey.fromExtendedKey(accountXpub);
  } catch (e) {
    throw new DerivationError(`invalid xpub: ${(e as Error).message}`);
  }
  const child = parent.derive(`m/${change}/${index}`);
  if (!child.publicKey) {
    throw new DerivationError("HDKey returned no public key");
  }
  const pub = child.publicKey;
  const h160 = hash160(pub);
  return {
    change,
    index,
    subPath: `${change}/${index}`,
    publicKey: pub,
    hash160: h160,
    address: encodeP2pkhAddress(h160),
  };
}

/**
 * Derive `count` consecutive addresses on `change` starting at `startIndex`.
 * Useful for receive UX ("show me my next 5 addresses").
 */
export function deriveAddressBatch(
  accountXpub: string,
  change: number,
  startIndex: number,
  count: number,
): DerivedAddress[] {
  if (!Number.isInteger(count) || count < 0 || count > 1000) {
    throw new DerivationError(`count out of range [0, 1000]: ${count}`);
  }
  const out: DerivedAddress[] = [];
  for (let i = 0; i < count; i++) {
    out.push(deriveAddress(accountXpub, change, startIndex + i));
  }
  return out;
}

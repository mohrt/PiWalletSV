import { describe, expect, it } from "vitest";

import { Hash, MerklePath, P2PKH, Transaction } from "@bsv/sdk";

import { tscProofToMerklePath } from "../src/lib/proof-fetcher.js";
import type { WocTxProof } from "../src/lib/woc.js";

const BLOCK_HEIGHT = 812345;

function reverseHex(hex: string): string {
  let out = "";
  for (let i = hex.length - 2; i >= 0; i -= 2) {
    out += hex.slice(i, i + 2);
  }
  return out;
}

function sha256dHex(a: string, b: string): string {
  // Bitcoin hashes are little-endian on the wire; the SDK works in big-endian
  // display form. Reverse, concat-bytes, double-SHA, reverse back.
  const ab = reverseHex(a) + reverseHex(b);
  const bytes = new Uint8Array(ab.length / 2);
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = parseInt(ab.slice(i * 2, i * 2 + 2), 16);
  }
  const once = Hash.sha256(bytes);
  const twice = Hash.sha256(once);
  let revHex = "";
  for (let i = twice.length - 1; i >= 0; i--) {
    revHex += twice[i].toString(16).padStart(2, "0");
  }
  return revHex;
}

function makeFundingTx(): Transaction {
  const tx = new Transaction();
  tx.addOutput({
    lockingScript: new P2PKH().lock("1K6LZdwpKT5XkEZo2T2kW197aMXYbYMc4f"),
    satoshis: 50_000,
  });
  return tx;
}

describe("tscProofToMerklePath", () => {
  it("constructs a 2-leaf path that verifies", () => {
    const funding = makeFundingTx();
    const txid = funding.id("hex") as string;
    const sibSeed = new TextEncoder().encode("piwallet-fixture-sibling-tx");
    const sibling = Hash.sha256(Hash.sha256(sibSeed));
    const siblingHex = Array.from(sibling)
      .reverse()
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
    const proof: WocTxProof = {
      txIndex: 0,
      blockHash: "00".repeat(32),
      nodes: [siblingHex],
    };
    const mp = tscProofToMerklePath(proof, txid, BLOCK_HEIGHT);
    expect(mp.blockHeight).toBe(BLOCK_HEIGHT);
    // txIndex=0 -> we're on the LEFT; sibling at offset 1 (right). Root = H(us, sib).
    expect(mp.computeRoot(txid)).toBe(sha256dHex(txid, siblingHex));
  });

  it("places sibling offsets per (txIndex >> level) ^ 1", () => {
    // txIndex = 5 (binary 101). Expected sibling offsets per level:
    //   L0: 5 ^ 1 = 4
    //   L1: 2 ^ 1 = 3
    //   L2: 1 ^ 1 = 0
    const proof: WocTxProof = {
      txIndex: 5,
      blockHash: "00".repeat(32),
      nodes: ["11".repeat(32), "22".repeat(32), "33".repeat(32)],
    };
    const mp = tscProofToMerklePath(proof, "ab".repeat(32), BLOCK_HEIGHT);
    expect(mp.path[0].find((e) => e.txid)?.offset).toBe(5);
    expect(mp.path[0].find((e) => !e.txid)?.offset).toBe(4);
    expect(mp.path[1][0].offset).toBe(3);
    expect(mp.path[2][0].offset).toBe(0);
  });

  it("encodes `*` node as duplicate", () => {
    const proof: WocTxProof = {
      txIndex: 0,
      blockHash: "00".repeat(32),
      nodes: ["*"],
    };
    const mp = tscProofToMerklePath(proof, "ab".repeat(32), BLOCK_HEIGHT);
    const sib = mp.path[0].find((e) => !e.txid);
    expect(sib?.duplicate).toBe(true);
    expect(sib?.hash).toBeUndefined();
  });

  it("uses fromCoinbaseTxidAndHeight for empty node lists", () => {
    const proof: WocTxProof = {
      txIndex: 0,
      blockHash: "00".repeat(32),
      nodes: [],
    };
    const mp = tscProofToMerklePath(proof, "aa".repeat(32), BLOCK_HEIGHT);
    expect(mp).toBeInstanceOf(MerklePath);
    expect(mp.blockHeight).toBe(BLOCK_HEIGHT);
  });
});

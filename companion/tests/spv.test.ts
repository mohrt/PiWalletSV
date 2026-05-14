import "fake-indexeddb/auto";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Hash } from "@bsv/sdk";

import { hexToBytes, bytesToHex } from "../src/lib/envelope.js";
import {
  HEADER_SIZE,
  checkpointFor,
  clearHeaderCache,
  headerHash,
  parseHeader,
  verifyPow,
  type CheckpointHeader,
  type WocHeaderJson,
} from "../src/lib/headers.js";
import { verifyUtxoSpv } from "../src/lib/spv.js";
import type { WalletUtxo } from "../src/lib/utxo.js";
import type {
  FetchFn,
  WocBulkUnspentResult,
  WocBlockHeader,
  WocHeaderJsonShape,
  WocTxProof,
} from "../src/lib/woc.js";
import { WocClient, WocError } from "../src/lib/woc.js";

const EASY_BITS = 0x207fffff;

function u32le(value: number, out: Uint8Array, offset: number): void {
  out[offset] = value & 0xff;
  out[offset + 1] = (value >>> 8) & 0xff;
  out[offset + 2] = (value >>> 16) & 0xff;
  out[offset + 3] = (value >>> 24) & 0xff;
}

function mineHeader(
  prevHash: Uint8Array,
  merkleRoot: Uint8Array,
  time: number,
): Uint8Array {
  const out = new Uint8Array(HEADER_SIZE);
  u32le(1, out, 0);
  out.set(prevHash, 4);
  out.set(merkleRoot, 36);
  u32le(time, out, 68);
  u32le(EASY_BITS, out, 72);
  for (let nonce = 0; nonce < 1 << 16; nonce++) {
    u32le(nonce, out, 76);
    try {
      verifyPow(parseHeader(out));
      return out;
    } catch {
      // try next nonce
    }
  }
  throw new Error("mineHeader: no nonce found");
}

/** Hash two displayed-hex hashes per the BSV merkle-tree convention. */
function combineHashesHex(aHex: string, bHex: string): string {
  const a = hexToBytes(aHex).reverse();
  const b = hexToBytes(bHex).reverse();
  const concat = new Uint8Array(64);
  concat.set(a, 0);
  concat.set(b, 32);
  const once = new Uint8Array(Hash.sha256(concat));
  const twice = new Uint8Array(Hash.sha256(once));
  return bytesToHex(twice.reverse());
}

/**
 * Build the synthetic chain we want for SPV: a single block at
 * `checkpoint.height + 1` that contains exactly two transactions —
 * the funding tx (txIndex=0) we'll verify, plus a sibling.
 *
 * Returns the chain plus the sibling hash (used to seed the proof).
 */
function buildOneBlockFixture(opts: { txid: string; sibling: string }): {
  checkpoint: CheckpointHeader;
  rawHeader: Uint8Array;
  blockHash: string;
  merkleRoot: string;
} {
  const checkpoint = checkpointFor("test");
  const rootDisplayHex = combineHashesHex(opts.txid, opts.sibling);
  const merkleRootBytes = hexToBytes(rootDisplayHex).reverse();
  const rawHeader = mineHeader(checkpoint.hash, merkleRootBytes, 1_700_000_000);
  return {
    checkpoint,
    rawHeader,
    blockHash: bytesToHex(headerHash(rawHeader).slice().reverse()),
    merkleRoot: rootDisplayHex,
  };
}

interface StubBackend {
  fetch: FetchFn;
  /** Override the proof for a specific txid (default = honest proof). */
  withProof(txid: string, proof: WocTxProof | null): void;
}

function makeStubBackend(opts: {
  rawHeader: Uint8Array;
  blockHash: string;
  utxo: WalletUtxo;
  honestProof: WocTxProof;
}): StubBackend {
  const proofs = new Map<string, WocTxProof | null>();
  proofs.set(opts.utxo.txid, opts.honestProof);
  const checkpoint = checkpointFor("test");
  const fetch: FetchFn = (input) => {
    const url = typeof input === "string" ? input : input.toString();

    // /block/{height}/header — header chain fetch.
    const heightMatch = url.match(/\/block\/(\d+)\/header$/);
    if (heightMatch) {
      const h = Number(heightMatch[1]);
      if (h !== checkpoint.height + 1) {
        return Promise.resolve(
          new Response(`no block at height ${h}`, { status: 404 }),
        );
      }
      const parsed = parseHeader(opts.rawHeader);
      const json: WocHeaderJsonShape = {
        hash: opts.blockHash,
        height: h,
        version: parsed.version,
        bits: parsed.bits.toString(16).padStart(8, "0"),
        nonce: parsed.nonce,
        merkleroot: bytesToHex(parsed.merkleRoot.slice().reverse()),
        time: parsed.time,
        previousblockhash: bytesToHex(parsed.prevHash.slice().reverse()),
      };
      return Promise.resolve(jsonResponse(json));
    }

    // /tx/{txid}/proof/tsc — TSC (BRC-10) Merkle proof.
    const proofMatch = url.match(/\/tx\/([0-9a-f]+)\/proof\/tsc$/i);
    if (proofMatch) {
      const txid = proofMatch[1].toLowerCase();
      const proof = proofs.get(txid);
      if (proof === null) {
        return Promise.resolve(
          new Response("not found", { status: 404 }),
        );
      }
      if (proof === undefined) {
        return Promise.resolve(
          new Response("not stubbed", { status: 404 }),
        );
      }
      return Promise.resolve(
        jsonResponse([
          {
            index: proof.txIndex,
            target: proof.blockHash,
            nodes: proof.nodes,
          },
        ]),
      );
    }

    return Promise.resolve(
      new Response(`unstubbed: ${url}`, { status: 500 }),
    );
  };

  return {
    fetch,
    withProof(txid, proof) {
      proofs.set(txid.toLowerCase(), proof);
    },
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const TXID = "ab".repeat(32);
const SIBLING = "cd".repeat(32);

const UTXO: WalletUtxo = {
  txid: TXID,
  vout: 0,
  sats: 50_000,
  height: -1, // filled in once we know the chain
  address: "n2EZJj8GgXaQjg5BcHwUwbT6V1KsX1pUzm",
  derivation: [0, 0],
};

describe("verifyUtxoSpv (receive-side BRC-67 SPV)", () => {
  beforeEach(async () => {
    await clearHeaderCache();
  });
  afterEach(async () => {
    await clearHeaderCache();
  });

  it("marks a UTXO as SPV-verified when the proof matches the validated chain root", async () => {
    const fixture = buildOneBlockFixture({ txid: TXID, sibling: SIBLING });
    const utxo: WalletUtxo = { ...UTXO, height: fixture.checkpoint.height + 1 };
    const backend = makeStubBackend({
      rawHeader: fixture.rawHeader,
      blockHash: fixture.blockHash,
      utxo,
      honestProof: {
        txIndex: 0,
        blockHash: fixture.blockHash,
        nodes: [SIBLING],
      },
    });
    const woc = new WocClient({
      fetch: backend.fetch,
      minIntervalMs: 0,
      maxRetries: 0,
    });
    const summary = await verifyUtxoSpv([utxo], woc, "test");

    expect(summary.verifiedCount).toBe(1);
    expect(summary.failedCount).toBe(0);
    expect(summary.pendingCount).toBe(0);
    expect(summary.verifiedSats).toBe(utxo.sats);
    expect(summary.failedSats).toBe(0);
    expect(summary.utxos[0].spvVerified).toBe(true);
    expect(summary.utxos[0].spvError).toBeUndefined();
  });

  it("refuses to verify a UTXO whose proof recomputes to a different root", async () => {
    const fixture = buildOneBlockFixture({ txid: TXID, sibling: SIBLING });
    const utxo: WalletUtxo = { ...UTXO, height: fixture.checkpoint.height + 1 };
    const backend = makeStubBackend({
      rawHeader: fixture.rawHeader,
      blockHash: fixture.blockHash,
      utxo,
      // Honest proof, then we override with a tampered sibling.
      honestProof: {
        txIndex: 0,
        blockHash: fixture.blockHash,
        nodes: [SIBLING],
      },
    });
    backend.withProof(TXID, {
      txIndex: 0,
      blockHash: fixture.blockHash,
      nodes: ["ee".repeat(32)], // different sibling => different root
    });
    const woc = new WocClient({
      fetch: backend.fetch,
      minIntervalMs: 0,
      maxRetries: 0,
    });
    const summary = await verifyUtxoSpv([utxo], woc, "test");

    expect(summary.verifiedCount).toBe(0);
    expect(summary.failedCount).toBe(1);
    expect(summary.failedSats).toBe(utxo.sats);
    expect(summary.utxos[0].spvVerified).toBe(false);
    expect(summary.utxos[0].spvError).toMatch(
      /(merkle|root|validated-chain)/i,
    );
  });

  it("flags a confirmed UTXO whose height isn't covered by the validated chain", async () => {
    const fixture = buildOneBlockFixture({ txid: TXID, sibling: SIBLING });
    // UTXO claims a height *past* the block we built.
    const utxo: WalletUtxo = { ...UTXO, height: fixture.checkpoint.height + 1 };
    const backend = makeStubBackend({
      rawHeader: fixture.rawHeader,
      blockHash: fixture.blockHash,
      utxo,
      honestProof: {
        txIndex: 0,
        blockHash: fixture.blockHash,
        nodes: [SIBLING],
      },
    });
    // Lie about the height of the UTXO so the chain we ensured doesn't
    // reach it. This mimics WoC reporting a stale height that we
    // can't anchor in the validated chain.
    const tamperedUtxo: WalletUtxo = {
      ...utxo,
      height: fixture.checkpoint.height + 99,
    };
    const woc = new WocClient({
      fetch: backend.fetch,
      minIntervalMs: 0,
      maxRetries: 0,
    });
    await expect(verifyUtxoSpv([tamperedUtxo], woc, "test")).rejects.toThrow();
  });

  it("passes through pending UTXOs without contacting the proof endpoint", async () => {
    let proofCalls = 0;
    const fetch: FetchFn = (input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.match(/\/tx\/[^/]+\/proof$/)) {
        proofCalls += 1;
        return Promise.resolve(jsonResponse({}, 404));
      }
      // Header fetch isn't needed because the deepest confirmed
      // height is 0; ensureChain stops at the checkpoint.
      return Promise.resolve(
        new Response("unexpected", { status: 500 }),
      );
    };
    const woc = new WocClient({ fetch, minIntervalMs: 0, maxRetries: 0 });
    const pending: WalletUtxo = { ...UTXO, height: 0 };
    const summary = await verifyUtxoSpv([pending], woc, "test");
    expect(summary.pendingCount).toBe(1);
    expect(summary.pendingSats).toBe(pending.sats);
    expect(summary.verifiedCount).toBe(0);
    expect(summary.failedCount).toBe(0);
    expect(summary.utxos[0].pending).toBe(true);
    expect(summary.utxos[0].spvVerified).toBe(false);
    expect(proofCalls).toBe(0);
  });

  // The receive-side regression check the plan calls out: "balance
  // refuses to count a UTXO whose proof doesn't validate". The
  // verifiedSats total is what the wallet UI uses for the trusted
  // confirmed-balance figure; an unverified UTXO must not contribute.
  it("verifiedSats excludes any confirmed UTXO that fails SPV", async () => {
    const fixture = buildOneBlockFixture({ txid: TXID, sibling: SIBLING });
    const baseUtxo: WalletUtxo = {
      ...UTXO,
      height: fixture.checkpoint.height + 1,
    };
    const otherTxid = "12".repeat(32);
    const otherUtxo: WalletUtxo = {
      ...UTXO,
      txid: otherTxid,
      vout: 1,
      sats: 1234,
      height: fixture.checkpoint.height + 1,
    };
    const backend = makeStubBackend({
      rawHeader: fixture.rawHeader,
      blockHash: fixture.blockHash,
      utxo: baseUtxo,
      honestProof: {
        txIndex: 0,
        blockHash: fixture.blockHash,
        nodes: [SIBLING],
      },
    });
    // The 2nd UTXO has no honest proof in this block — return a
    // mismatched proof to simulate a hostile WoC.
    backend.withProof(otherTxid, {
      txIndex: 0,
      blockHash: fixture.blockHash,
      nodes: ["aa".repeat(32)],
    });
    const woc = new WocClient({
      fetch: backend.fetch,
      minIntervalMs: 0,
      maxRetries: 0,
    });
    const summary = await verifyUtxoSpv([baseUtxo, otherUtxo], woc, "test");
    expect(summary.verifiedSats).toBe(baseUtxo.sats);
    expect(summary.failedSats).toBe(otherUtxo.sats);
    expect(summary.verifiedSats + summary.failedSats).toBe(
      baseUtxo.sats + otherUtxo.sats,
    );
  });
});

// Silence unused-import lint for type re-exports we want available
// to copy-paste consumers but didn't end up needing in this file.
const _typeKeepalive: [
  WocBulkUnspentResult?,
  WocBlockHeader?,
  WocHeaderJson?,
  WocError?,
] = [];
void _typeKeepalive;

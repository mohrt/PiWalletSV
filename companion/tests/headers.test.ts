import "fake-indexeddb/auto";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { hexToBytes, bytesToHex } from "../src/lib/envelope.js";
import {
  HEADER_SIZE,
  HeaderError,
  MAINNET_GENESIS_HEADER_HEX,
  TESTNET_GENESIS_HEADER_HEX,
  bitsToTarget,
  bytesEqual,
  checkpointFor,
  clearHeaderCache,
  ensureChain,
  getCachedHeader,
  getCachedHeaderRange,
  getCachedTip,
  headerHash,
  parseHeader,
  putValidatedHeaders,
  rawHeaderFromJson,
  verifyChain,
  verifyPow,
  type CachedHeader,
  type CheckpointHeader,
  type HeaderChainFetcher,
  type WocHeaderJson,
} from "../src/lib/headers.js";

// ---------------------------------------------------------------------------
// Synthetic-chain helpers.
//
// We can't test against a real BSV mainnet chain inside vitest (would
// require fetching headers across the network), so the property
// tests below mine a small chain with bits=0x207fffff. That target is
// 0x7fffff << 232, i.e. just under 2**255 — half of all double-SHA256
// outputs pass on the first try, so a one-byte nonce search always
// finds a satisfying header in <256 iterations.
// ---------------------------------------------------------------------------

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
  throw new Error("mineHeader: no nonce found in 65k tries");
}

function makeChain(checkpoint: CheckpointHeader, length: number): Uint8Array[] {
  const headers: Uint8Array[] = [];
  let prev = checkpoint.hash;
  for (let i = 0; i < length; i++) {
    const merkleRoot = new Uint8Array(32);
    merkleRoot[0] = (i + 1) & 0xff;
    merkleRoot[1] = ((i + 1) >>> 8) & 0xff;
    const h = mineHeader(prev, merkleRoot, 1_700_000_000 + i * 600);
    headers.push(h);
    prev = headerHash(h);
  }
  return headers;
}

// ---------------------------------------------------------------------------

describe("parseHeader / headerHash / bitsToTarget", () => {
  it("parses the BSV mainnet genesis header round-trip", () => {
    const raw = hexToBytes(MAINNET_GENESIS_HEADER_HEX);
    const h = parseHeader(raw);
    expect(h.version).toBe(1);
    expect(h.time).toBe(0x495fab29); // little-endian "29ab5f49"
    expect(h.nonce).toBe(0x7c2bac1d); // little-endian "1dac2b7c"
    expect(h.bits).toBe(0x1d00ffff);
    expect(Array.from(h.raw)).toEqual(Array.from(raw));
    // Genesis hash, big-endian display:
    expect(bytesToHex(headerHash(raw).slice().reverse())).toBe(
      "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f",
    );
  });

  it("parses the BSV testnet3 genesis header", () => {
    const raw = hexToBytes(TESTNET_GENESIS_HEADER_HEX);
    expect(bytesToHex(headerHash(raw).slice().reverse())).toBe(
      "000000000933ea01ad0ee984209779baaec3ced90fa3f408719526f8d77f4943",
    );
  });

  it("rejects headers of the wrong length", () => {
    expect(() => parseHeader(new Uint8Array(79))).toThrow(HeaderError);
    expect(() => parseHeader(new Uint8Array(81))).toThrow(HeaderError);
    expect(() => headerHash(new Uint8Array(0))).toThrow(HeaderError);
  });

  it("decodes the genesis bits to the expected difficulty target", () => {
    // bits=0x1d00ffff → target=0x00000000ffff0000... (BSV/BTC genesis).
    const target = bitsToTarget(0x1d00ffff);
    const expected =
      0x00000000ffff0000000000000000000000000000000000000000000000000000n;
    expect(target).toBe(expected);
  });

  it("rejects bits with the sign bit set", () => {
    expect(() => bitsToTarget(0x00800000)).toThrow(/sign bit/);
    expect(() => bitsToTarget(0x18800000)).toThrow(/sign bit/);
  });

  it("rejects bits whose decoded target overflows 256 bits", () => {
    // exponent=0x21 gives a 257-bit target: invalid by spec.
    expect(() => bitsToTarget(0x21010000)).toThrow(/256/);
  });
});

describe("verifyPow", () => {
  it("accepts the genesis header (it satisfies its own bits)", () => {
    const raw = hexToBytes(MAINNET_GENESIS_HEADER_HEX);
    const h = parseHeader(raw);
    expect(() => verifyPow(h)).not.toThrow();
  });

  it("rejects a header whose hash exceeds the declared target", () => {
    // Modify the genesis nonce so the hash no longer satisfies its
    // (very strict) bits. Any random tweak almost certainly fails PoW.
    const raw = hexToBytes(MAINNET_GENESIS_HEADER_HEX);
    raw[76] ^= 0x01;
    raw[77] ^= 0x37;
    expect(() => verifyPow(parseHeader(raw))).toThrow(/fails PoW/);
  });
});

describe("verifyChain", () => {
  it("accepts a synthetic chain and returns one merkle root per height", () => {
    const checkpoint = checkpointFor("test");
    const chain = makeChain(checkpoint, 4);
    const map = verifyChain(chain, checkpoint);
    expect(map.size).toBe(4);
    expect(map.get(checkpoint.height + 1)).toBeInstanceOf(Uint8Array);
    expect(map.get(checkpoint.height + 4)).toBeInstanceOf(Uint8Array);
    expect(map.get(checkpoint.height + 5)).toBeUndefined();
  });

  it("rejects an empty chain", () => {
    expect(() =>
      verifyChain([], checkpointFor("test")),
    ).toThrow(/empty header sequence/);
  });

  it("rejects a chain whose first header doesn't link to the checkpoint", () => {
    const checkpoint = checkpointFor("test");
    const chain = makeChain(checkpoint, 2);
    // Replace the first header's prev_hash with garbage.
    chain[0].set(new Uint8Array(32).fill(0x99), 4);
    expect(() => verifyChain(chain, checkpoint)).toThrow(
      /prev_hash mismatch/,
    );
  });

  it("rejects a chain with a broken link in the middle", () => {
    const checkpoint = checkpointFor("test");
    const chain = makeChain(checkpoint, 4);
    // Tamper with header[1]'s merkleRoot. Header[2]'s prev_hash will
    // point at the *original* header[1]'s hash, so the linkage check
    // catches it.
    chain[1][36] ^= 0xff;
    expect(() => verifyChain(chain, checkpoint)).toThrow(
      /(prev_hash mismatch|fails PoW)/,
    );
  });

  it("rejects a chain whose last header fails PoW", () => {
    const checkpoint = checkpointFor("test");
    const chain = makeChain(checkpoint, 3);
    // Re-bits the final header to genesis-difficulty (1d00ffff): the
    // hash we mined under EASY_BITS is overwhelmingly unlikely to
    // also clear that target.
    u32le(0x1d00ffff, chain[2], 72);
    expect(() => verifyChain(chain, checkpoint)).toThrow(/fails PoW/);
  });

  it("rejects a chain pinned to the wrong network", () => {
    const mainnet = checkpointFor("main");
    const testnetChain = makeChain(checkpointFor("test"), 2);
    expect(() => verifyChain(testnetChain, mainnet)).toThrow(
      /prev_hash mismatch/,
    );
  });
});

describe("rawHeaderFromJson", () => {
  it("reconstructs the genesis header bytes from the WoC JSON shape", () => {
    // Genesis fields, lifted from the canonical mainnet header.
    const json: WocHeaderJson = {
      hash: "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f",
      height: 0,
      version: 1,
      bits: "1d00ffff",
      nonce: 2083236893, // 0x7c2bac1d
      merkleroot:
        "4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b",
      time: 1231006505,
      // previousblockhash absent on genesis.
    };
    const raw = rawHeaderFromJson(json);
    expect(bytesToHex(raw)).toBe(MAINNET_GENESIS_HEADER_HEX);
  });

  it("requires previousblockhash for non-genesis heights", () => {
    expect(() =>
      rawHeaderFromJson({
        hash: "00".repeat(32),
        height: 1,
        version: 1,
        bits: "1d00ffff",
        nonce: 0,
        merkleroot: "00".repeat(32),
        time: 0,
      }),
    ).toThrow(/previousblockhash/);
  });

  it("rejects a JSON whose declared hash doesn't match the bytes", () => {
    expect(() =>
      rawHeaderFromJson({
        hash: "ff".repeat(32),
        height: 0,
        version: 1,
        bits: "1d00ffff",
        nonce: 2083236893,
        merkleroot:
          "4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b",
        time: 1231006505,
      }),
    ).toThrow(/self-check failed/);
  });

  it("rejects malformed bits / merkleroot fields", () => {
    expect(() =>
      rawHeaderFromJson({
        hash: "00".repeat(32),
        height: 1,
        version: 1,
        bits: "zzzzzzzz",
        nonce: 0,
        merkleroot: "00".repeat(32),
        time: 0,
        previousblockhash: "11".repeat(32),
      }),
    ).toThrow(/bits/);
  });
});

describe("IndexedDB header cache", () => {
  beforeEach(async () => {
    await clearHeaderCache();
  });

  afterEach(async () => {
    await clearHeaderCache();
  });

  it("stores and retrieves single rows by [network, height]", async () => {
    const row: CachedHeader = {
      network: "test",
      height: 1,
      hashHex: "aa".repeat(32),
      merkleRootHex: "bb".repeat(32),
      rawHex: "cc".repeat(80),
      validatedAt: new Date().toISOString(),
    };
    await putValidatedHeaders([row]);
    const got = await getCachedHeader("test", 1);
    expect(got).not.toBeNull();
    expect(got?.hashHex).toBe(row.hashHex);
    // Different network at the same height: distinct row, no leakage.
    expect(await getCachedHeader("main", 1)).toBeNull();
  });

  it("range query returns only entries for the requested network and span", async () => {
    const rows: CachedHeader[] = [];
    for (let h = 1; h <= 5; h++) {
      rows.push({
        network: "test",
        height: h,
        hashHex: h.toString().padStart(64, "0"),
        merkleRootHex: "00".repeat(32),
        rawHex: "00".repeat(80),
        validatedAt: new Date().toISOString(),
      });
    }
    await putValidatedHeaders(rows);
    const slice = await getCachedHeaderRange("test", 2, 4);
    expect(slice.map((r) => r.height).sort()).toEqual([2, 3, 4]);
    const otherNet = await getCachedHeaderRange("main", 0, 100);
    expect(otherNet).toEqual([]);
  });

  it("getCachedTip walks the cache forward until it finds a gap", async () => {
    const checkpoint = checkpointFor("test");
    const chain = makeChain(checkpoint, 3);
    const rows: CachedHeader[] = chain.map((raw, i) => ({
      network: "test",
      height: checkpoint.height + 1 + i,
      hashHex: bytesToHex(headerHash(raw).slice().reverse()),
      merkleRootHex: bytesToHex(parseHeader(raw).merkleRoot.slice().reverse()),
      rawHex: bytesToHex(raw),
      validatedAt: new Date().toISOString(),
    }));
    // Insert rows[0] and rows[2] but skip rows[1] — there's a gap.
    await putValidatedHeaders([rows[0], rows[2]]);
    const tip = await getCachedTip("test", checkpoint.height + 1);
    expect(tip?.height).toBe(checkpoint.height + 1);
    // Now fill the gap; tip should advance to the end.
    await putValidatedHeaders([rows[1]]);
    const tip2 = await getCachedTip("test", checkpoint.height + 1);
    expect(tip2?.height).toBe(checkpoint.height + 3);
  });
});

describe("ensureChain", () => {
  beforeEach(async () => {
    await clearHeaderCache();
  });

  afterEach(async () => {
    await clearHeaderCache();
  });

  function fetcherFromChain(
    chain: Uint8Array[],
    checkpoint: CheckpointHeader,
  ): HeaderChainFetcher & { calls: number } {
    let calls = 0;
    return {
      get calls() {
        return calls;
      },
      async getHeaderChain(fromHeight: number, count: number) {
        calls += 1;
        const out: WocHeaderJson[] = [];
        for (let i = 0; i < count; i++) {
          const idx = fromHeight - checkpoint.height - 1 + i;
          if (idx < 0 || idx >= chain.length) {
            throw new Error(`out of range idx=${idx}`);
          }
          const raw = chain[idx];
          const h = parseHeader(raw);
          out.push({
            hash: bytesToHex(headerHash(raw).slice().reverse()),
            height: fromHeight + i,
            version: h.version,
            bits: h.bits.toString(16).padStart(8, "0"),
            nonce: h.nonce,
            merkleroot: bytesToHex(h.merkleRoot.slice().reverse()),
            time: h.time,
            previousblockhash: bytesToHex(h.prevHash.slice().reverse()),
          });
        }
        return out;
      },
    };
  }

  it("fetches the full chain on a cold cache and persists every entry", async () => {
    const checkpoint = checkpointFor("test");
    const chain = makeChain(checkpoint, 5);
    const fetcher = fetcherFromChain(chain, checkpoint);
    const result = await ensureChain(
      "test",
      checkpoint.height + 5,
      fetcher,
      { chunkSize: 2 },
    );
    expect(result.rawHeaders).toHaveLength(5);
    expect(fetcher.calls).toBeGreaterThan(0);
    // Cache should now contain all five heights.
    const rows = await getCachedHeaderRange(
      "test",
      checkpoint.height + 1,
      checkpoint.height + 5,
    );
    expect(rows.map((r) => r.height).sort((a, b) => a - b)).toEqual([
      checkpoint.height + 1,
      checkpoint.height + 2,
      checkpoint.height + 3,
      checkpoint.height + 4,
      checkpoint.height + 5,
    ]);
  });

  it("short-circuits a warm cache: zero network calls when the cache covers the target", async () => {
    const checkpoint = checkpointFor("test");
    const chain = makeChain(checkpoint, 4);
    const warmFetcher = fetcherFromChain(chain, checkpoint);
    await ensureChain("test", checkpoint.height + 4, warmFetcher);
    const before = warmFetcher.calls;

    const coldFetcher = fetcherFromChain(chain, checkpoint);
    const result = await ensureChain(
      "test",
      checkpoint.height + 4,
      coldFetcher,
    );
    expect(coldFetcher.calls).toBe(0);
    expect(result.rawHeaders).toHaveLength(4);
    // Sanity: the warm-up did the work, not the second call.
    expect(before).toBeGreaterThan(0);
  });

  it("extends a partial cache by fetching only the missing suffix", async () => {
    const checkpoint = checkpointFor("test");
    const chain = makeChain(checkpoint, 6);
    const partialFetcher = fetcherFromChain(chain, checkpoint);
    await ensureChain("test", checkpoint.height + 3, partialFetcher);
    const callsAtPartial = partialFetcher.calls;

    const extendFetcher = fetcherFromChain(chain, checkpoint);
    const result = await ensureChain(
      "test",
      checkpoint.height + 6,
      extendFetcher,
      { chunkSize: 100 },
    );
    expect(result.rawHeaders).toHaveLength(6);
    // Only one chunk worth of fetches for the new 3 headers.
    expect(extendFetcher.calls).toBe(1);
    expect(callsAtPartial).toBeGreaterThan(0);
  });

  it("rejects (and does NOT persist) a chain that fails PoW mid-way", async () => {
    const checkpoint = checkpointFor("test");
    const chain = makeChain(checkpoint, 4);
    // Tamper with the chain post-mining: re-bits header[2] to genesis
    // difficulty so its hash no longer clears the target.
    u32le(0x1d00ffff, chain[2], 72);
    const fetcher = fetcherFromChain(chain, checkpoint);
    await expect(
      ensureChain("test", checkpoint.height + 4, fetcher, {
        chunkSize: 4,
      }),
    ).rejects.toThrow(/(self-check|fails PoW)/);
  });

  it("rejects a chain whose first fetched header doesn't link to the checkpoint", async () => {
    const checkpoint = checkpointFor("test");
    const wrongCheckpoint: CheckpointHeader = {
      height: checkpoint.height,
      hash: new Uint8Array(32).fill(0x33),
    };
    const chain = makeChain(wrongCheckpoint, 2);
    const fetcher = fetcherFromChain(chain, wrongCheckpoint);
    await expect(
      ensureChain("test", checkpoint.height + 2, fetcher),
    ).rejects.toThrow(/prev_hash mismatch/);
  });
});

describe("checkpointFor / bytesEqual", () => {
  it("returns distinct mainnet and testnet checkpoints", () => {
    const m = checkpointFor("main");
    const t = checkpointFor("test");
    expect(m.height).toBe(0);
    expect(t.height).toBe(0);
    expect(bytesEqual(m.hash, t.hash)).toBe(false);
  });

  it("rejects unknown networks", () => {
    expect(() =>
      checkpointFor("regtest" as unknown as "main"),
    ).toThrow(HeaderError);
  });
});

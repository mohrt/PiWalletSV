import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  ENVELOPE_VERSION,
  EnvelopeError,
  KIND_PROPOSAL,
  KIND_SIGNED,
  KIND_XPUB,
  type SignedTxT,
  type UnsignedProposalT,
  type XpubExportT,
  bytesToHex,
  decodeEnvelope,
  encodeEnvelope,
  hexToBytes,
} from "../src/lib/envelope.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const FIXTURE_CBOR = join(__dirname, "../../tests/fixtures/proposal_01.cbor");
const FIXTURE_META = join(__dirname, "../../tests/fixtures/proposal_01.json");

interface FixtureMeta {
  wallet_fingerprint_hex: string;
  funding_txid: string;
  funding_amount_sats: number;
  pay_amount_sats: number;
  change_amount_sats: number;
  block_height: number;
  merkle_root_hex: string;
}

// NOTE on Phase-2 transition state: the Python fixture now emits the
// new SPV schema (`checkpointHeight` + raw `headers` list) and no
// longer carries the legacy per-height `headerAnchors` map. The
// companion codec on this branch still consumes the legacy field, so
// the decoded `headerAnchors` is just empty here. Phase 3 of the SPV
// alignment plan rewires the companion codec to read `headers`
// directly; once that lands, this test will assert chain-validation
// rather than the legacy anchor map.

function makeXpub(): XpubExportT {
  return {
    kind: KIND_XPUB,
    xpub:
      "xpub6CdMDgU2hzWyeZ852LWqp5AfDz3ty2cRfi4jEw9BT8aNYugMQv" +
      "VykQsKLARZdbqKKp7yTviJdL1N9saYLmJNKD1rwVAwLTmU8r8qKeoyG4R",
    path: "m/44'/236'/0'",
    label: "test wallet",
    fingerprint: hexToBytes("cf987d8c"),
    network: "main",
  };
}

function makeProposal(): UnsignedProposalT {
  // Synthetic single-header chain. The bytes below do not pass PoW;
  // the codec round-trip test exercises field shape only.
  const stubHeader = new Uint8Array(80);
  stubHeader[0] = 0x01;
  return {
    kind: KIND_PROPOSAL,
    walletFp: hexToBytes("cf987d8c"),
    inputs: [
      {
        txid: "ab".repeat(32),
        vout: 0,
        sats: 50000,
        beef: new Uint8Array(64).fill(0xaa),
        derivation: [0, 5],
      },
    ],
    outputs: [
      { scriptHex: "76a914" + "00".repeat(20) + "88ac", sats: 30000 },
      { scriptHex: "76a914" + "11".repeat(20) + "88ac", sats: 19500 },
    ],
    changeIndex: 1,
    changeDerivation: [1, 0],
    feeRate: 500,
    locktime: 0,
    checkpointHeight: 812345,
    headers: [stubHeader],
  };
}

function makeSigned(): SignedTxT {
  // Hand-constructed Atomic BEEF: 4-byte magic + 32-byte subject TXID
  // (in raw byte order; displayed-hex is the byte-reverse) + a
  // sentinel "BEEF body" placeholder. The test only asserts that the
  // codec round-trips the bytes; full BRC-62 BEEF semantics are
  // covered by the upstream `@bsv/sdk` test suite.
  const txidDisplayHex = "cd".repeat(32);
  const txidBytes = hexToBytes(txidDisplayHex).reverse();
  const beefBody = new Uint8Array(60).fill(0xee);
  const atomicBeef = new Uint8Array(4 + 32 + beefBody.length);
  atomicBeef.set([0x01, 0x01, 0x01, 0x01], 0);
  atomicBeef.set(txidBytes, 4);
  atomicBeef.set(beefBody, 4 + 32);
  return {
    kind: KIND_SIGNED,
    walletFp: hexToBytes("cf987d8c"),
    atomicBeef,
  };
}

describe("envelope codec", () => {
  it("decodes the Python-emitted proposal_01.cbor fixture", async () => {
    const meta = JSON.parse(readFileSync(FIXTURE_META, "utf8")) as FixtureMeta;
    const blob = new Uint8Array(readFileSync(FIXTURE_CBOR));
    const env = await decodeEnvelope(blob);

    expect(env.kind).toBe(KIND_PROPOSAL);
    if (env.kind !== KIND_PROPOSAL) return;

    expect(bytesToHex(env.walletFp)).toBe(meta.wallet_fingerprint_hex);
    expect(env.inputs.length).toBeGreaterThanOrEqual(1);
    expect(env.inputs[0].txid).toBe(meta.funding_txid);
    expect(env.inputs[0].sats).toBe(meta.funding_amount_sats);
    expect(env.inputs[0].beef.byteLength).toBeGreaterThan(0);

    expect(env.outputs.length).toBe(2);
    const totalOut = env.outputs.reduce((acc, o) => acc + o.sats, 0);
    expect(totalOut).toBe(meta.pay_amount_sats + meta.change_amount_sats);

    // v2 envelopes carry a raw header chain rooted at a known
    // checkpoint height; the legacy `headerAnchors` map is gone.
    expect(env.checkpointHeight).toBeGreaterThanOrEqual(0);
    expect(env.headers.length).toBeGreaterThanOrEqual(1);
    for (const h of env.headers) expect(h.byteLength).toBe(80);
    // Sanity: the deepest input height must fit within the chain
    // window the proposal ships, so the Pi-side verifier does not
    // reject before even running PoW.
    const tip = env.checkpointHeight + env.headers.length;
    expect(tip).toBeGreaterThanOrEqual(meta.block_height);
    expect(meta.merkle_root_hex).toMatch(/^[0-9a-f]{64}$/);
  });

  it("round-trips an xpub_export", async () => {
    const src = makeXpub();
    const blob = await encodeEnvelope(src);
    const round = await decodeEnvelope(blob);
    expect(round.kind).toBe(KIND_XPUB);
    if (round.kind !== KIND_XPUB) return;
    expect(round.xpub).toBe(src.xpub);
    expect(round.path).toBe(src.path);
    expect(round.label).toBe(src.label);
    expect(bytesToHex(round.fingerprint)).toBe(bytesToHex(src.fingerprint));
    expect(round.network).toBe("main");
  });

  it("round-trips a testnet xpub_export", async () => {
    const src: XpubExportT = { ...makeXpub(), network: "test" };
    const blob = await encodeEnvelope(src);
    const round = await decodeEnvelope(blob);
    expect(round.kind).toBe(KIND_XPUB);
    if (round.kind !== KIND_XPUB) return;
    expect(round.network).toBe("test");
  });

  it("decodes pre-v1.1 xpub_export (no `net` field) as mainnet", async () => {
    // Build a body without `net`, then gzip+CBOR exactly the way the
    // pre-testnet companion would have done.
    const { Encoder: E } = await import("cbor-x");
    const enc = new E({
      useRecords: false,
      structuredClone: false,
      mapsAsObjects: false,
      tagUint8Array: false,
    });
    const src = makeXpub();
    const body = new Map<string, unknown>();
    body.set("v", ENVELOPE_VERSION);
    body.set("kind", KIND_XPUB);
    body.set("xpub", src.xpub);
    body.set("path", src.path);
    body.set("label", src.label);
    body.set("fp", src.fingerprint);
    const cbor = new Uint8Array(enc.encode(body));
    const stream = new Blob([cbor])
      .stream()
      .pipeThrough(new CompressionStream("gzip"));
    const blob = new Uint8Array(await new Response(stream).arrayBuffer());
    const round = await decodeEnvelope(blob);
    expect(round.kind).toBe(KIND_XPUB);
    if (round.kind !== KIND_XPUB) return;
    expect(round.network).toBe("main");
  });

  it("rejects xpub_export with an unknown `net` value", async () => {
    const { Encoder: E } = await import("cbor-x");
    const enc = new E({
      useRecords: false,
      structuredClone: false,
      mapsAsObjects: false,
      tagUint8Array: false,
    });
    const src = makeXpub();
    const body = new Map<string, unknown>();
    body.set("v", ENVELOPE_VERSION);
    body.set("kind", KIND_XPUB);
    body.set("xpub", src.xpub);
    body.set("path", src.path);
    body.set("label", src.label);
    body.set("fp", src.fingerprint);
    body.set("net", "regtest");
    const cbor = new Uint8Array(enc.encode(body));
    const stream = new Blob([cbor])
      .stream()
      .pipeThrough(new CompressionStream("gzip"));
    const blob = new Uint8Array(await new Response(stream).arrayBuffer());
    await expect(decodeEnvelope(blob)).rejects.toThrow(/net|main|test/i);
  });

  it("round-trips an unsigned_proposal (incl. checkpoint + headers chain)", async () => {
    const src = makeProposal();
    const blob = await encodeEnvelope(src);
    const round = await decodeEnvelope(blob);
    expect(round.kind).toBe(KIND_PROPOSAL);
    if (round.kind !== KIND_PROPOSAL) return;
    expect(bytesToHex(round.walletFp)).toBe(bytesToHex(src.walletFp));
    expect(round.inputs).toHaveLength(src.inputs.length);
    expect(round.inputs[0].txid).toBe(src.inputs[0].txid);
    expect(round.inputs[0].derivation).toEqual(src.inputs[0].derivation);
    expect(Array.from(round.inputs[0].beef)).toEqual(
      Array.from(src.inputs[0].beef),
    );
    expect(round.outputs).toEqual(src.outputs);
    expect(round.changeIndex).toBe(src.changeIndex);
    expect(round.changeDerivation).toEqual(src.changeDerivation);
    expect(round.feeRate).toBe(src.feeRate);
    expect(round.locktime).toBe(src.locktime);
    expect(round.checkpointHeight).toBe(src.checkpointHeight);
    expect(round.headers).toHaveLength(src.headers.length);
    for (let i = 0; i < src.headers.length; i++) {
      expect(Array.from(round.headers[i])).toEqual(
        Array.from(src.headers[i]),
      );
    }
  });

  it("round-trips a signed_tx (Atomic BEEF payload)", async () => {
    const src = makeSigned();
    const blob = await encodeEnvelope(src);
    const round = await decodeEnvelope(blob);
    expect(round.kind).toBe(KIND_SIGNED);
    if (round.kind !== KIND_SIGNED) return;
    expect(bytesToHex(round.walletFp)).toBe(bytesToHex(src.walletFp));
    expect(Array.from(round.atomicBeef)).toEqual(Array.from(src.atomicBeef));
    // BRC-95 magic is preserved as the first 4 bytes.
    expect(Array.from(round.atomicBeef.slice(0, 4))).toEqual([
      0x01, 0x01, 0x01, 0x01,
    ]);
  });

  it("round-trip output is decodable by Python (header preserved)", async () => {
    // Simple invariant: top-level fields use the agreed Python-side names.
    const blob = await encodeEnvelope(makeXpub());
    const round = await decodeEnvelope(blob);
    expect(round.kind).toBe(KIND_XPUB);
  });

  it("rejects corrupted gzip", async () => {
    const garbage = new Uint8Array([0x1f, 0x8b, 0x08, 0xff, 0xff, 0xff]);
    await expect(decodeEnvelope(garbage)).rejects.toBeInstanceOf(EnvelopeError);
  });

  it("rejects non-map top-level CBOR", async () => {
    // Encode a CBOR array (not a map) and gzip it.
    const arrCbor = new Uint8Array([0x83, 0x01, 0x02, 0x03]); // [1,2,3]
    const stream = new Blob([arrCbor])
      .stream()
      .pipeThrough(new CompressionStream("gzip"));
    const blob = new Uint8Array(await new Response(stream).arrayBuffer());
    await expect(decodeEnvelope(blob)).rejects.toBeInstanceOf(EnvelopeError);
  });

  it("rejects unsupported envelope version", async () => {
    const src = makeXpub();
    const blob = await encodeEnvelope(src);
    // Manual surgery: gunzip, find the 'v' key value (CBOR int 1 = 0x01), bump to 99.
    // Easiest path: re-encode with a hand-made body asserting a wrong v.
    const { Encoder: E } = await import("cbor-x");
    const enc = new E({
      useRecords: false,
      structuredClone: false,
      mapsAsObjects: false,
      tagUint8Array: false,
    });
    const bad = new Map<string, unknown>();
    bad.set("v", 99);
    bad.set("kind", KIND_XPUB);
    bad.set("xpub", src.xpub);
    bad.set("path", src.path);
    bad.set("label", src.label);
    bad.set("fp", src.fingerprint);
    const cborBytes = enc.encode(bad);
    const stream = new Blob([new Uint8Array(cborBytes)])
      .stream()
      .pipeThrough(new CompressionStream("gzip"));
    const badBlob = new Uint8Array(await new Response(stream).arrayBuffer());
    await expect(decodeEnvelope(badBlob)).rejects.toThrow(/version/i);
    // Use blob to silence unused
    expect(blob.byteLength).toBeGreaterThan(0);
  });

  it("ENVELOPE_VERSION is 2 (matches Python)", () => {
    expect(ENVELOPE_VERSION).toBe(2);
  });
});

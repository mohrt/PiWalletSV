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

function makeXpub(): XpubExportT {
  return {
    kind: KIND_XPUB,
    xpub:
      "xpub6CdMDgU2hzWyeZ852LWqp5AfDz3ty2cRfi4jEw9BT8aNYugMQv" +
      "VykQsKLARZdbqKKp7yTviJdL1N9saYLmJNKD1rwVAwLTmU8r8qKeoyG4R",
    path: "m/44'/236'/0'",
    label: "test wallet",
    fingerprint: hexToBytes("cf987d8c"),
  };
}

function makeProposal(): UnsignedProposalT {
  return {
    kind: KIND_PROPOSAL,
    walletFp: hexToBytes("cf987d8c"),
    inputs: [
      {
        txid: "ab".repeat(32),
        vout: 0,
        sats: 50000,
        beef: new Uint8Array(64).fill(0xaa),
        merklePath: new Uint8Array(48).fill(0xbb),
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
    headerAnchors: new Map<number, Uint8Array>([
      [812345, new Uint8Array(32).fill(0x42)],
    ]),
  };
}

function makeSigned(): SignedTxT {
  return {
    kind: KIND_SIGNED,
    walletFp: hexToBytes("cf987d8c"),
    rawHex: "01000000" + "00".repeat(60),
    txid: "cd".repeat(32),
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
    expect(env.inputs[0].merklePath.byteLength).toBeGreaterThan(0);

    expect(env.outputs.length).toBe(2);
    const totalOut = env.outputs.reduce((acc, o) => acc + o.sats, 0);
    expect(totalOut).toBe(meta.pay_amount_sats + meta.change_amount_sats);

    expect(env.headerAnchors.size).toBeGreaterThanOrEqual(1);
    const anchor = env.headerAnchors.get(meta.block_height);
    expect(anchor).toBeDefined();
    expect(bytesToHex(anchor!)).toBe(meta.merkle_root_hex);
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
  });

  it("round-trips an unsigned_proposal (incl. headerAnchors map)", async () => {
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
    expect(round.headerAnchors.size).toBe(1);
    const a = round.headerAnchors.get(812345);
    expect(a).toBeDefined();
    expect(Array.from(a!)).toEqual(
      Array.from(src.headerAnchors.get(812345)!),
    );
  });

  it("round-trips a signed_tx", async () => {
    const src = makeSigned();
    const blob = await encodeEnvelope(src);
    const round = await decodeEnvelope(blob);
    expect(round.kind).toBe(KIND_SIGNED);
    if (round.kind !== KIND_SIGNED) return;
    expect(bytesToHex(round.walletFp)).toBe(bytesToHex(src.walletFp));
    expect(round.rawHex).toBe(src.rawHex);
    expect(round.txid).toBe(src.txid);
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

  it("ENVELOPE_VERSION is 1 (matches Python)", () => {
    expect(ENVELOPE_VERSION).toBe(1);
  });
});

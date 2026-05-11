import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  KIND_PROPOSAL,
  bytesToHex,
  decodeEnvelope,
  encodeEnvelope,
} from "../src/lib/envelope.js";
import { selectUtxosGreedy } from "../src/lib/coin-select.js";
import type { InputProof } from "../src/lib/proof-fetcher.js";
import {
  ProposalBuilderError,
  buildUnsignedProposal,
} from "../src/lib/proposal.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const FIXTURE = JSON.parse(
  readFileSync(
    join(__dirname, "../../tests/fixtures/addresses_canonical.json"),
    "utf8",
  ),
) as { fingerprint: string; xpub: string };

// Canonical mainnet P2PKH addresses; we don't need real proofs here, just
// well-formed sentinel bytes so the envelope encodes and round-trips.
const RECIPIENT = "155Vurs4bMMu5BemtZ6cVPhryGWef4VxZu";
const CHANGE = "125GFsvYsDtyzGkExfsX8DoHuXu2UsMUEZ"; // m/1/0 for canonical xpub

function fakeProof(seed: number, height: number): InputProof {
  const root = new Uint8Array(32);
  for (let i = 0; i < 32; i++) root[i] = (seed + i) & 0xff;
  const merkleRoot = Array.from(root)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return {
    beef: new Uint8Array(64).map((_, i) => (seed * 7 + i) & 0xff),
    merklePath: new Uint8Array(48).map((_, i) => (seed * 11 + i) & 0xff),
    height,
    merkleRoot,
  };
}

describe("buildUnsignedProposal", () => {
  it("builds a 1-in/2-out proposal that round-trips through encode/decode", async () => {
    const env = buildUnsignedProposal({
      walletFingerprintHex: FIXTURE.fingerprint,
      inputs: [
        {
          txid: "aa".repeat(32),
          vout: 0,
          sats: 50_000,
          derivation: [0, 0],
          proof: fakeProof(1, 812345),
        },
      ],
      recipientAddress: RECIPIENT,
      recipientSats: 30_000,
      changeAddress: CHANGE,
      changeSats: 19_500,
      changeDerivation: [1, 0],
      feeRateSatskb: 500,
      locktime: 0,
    });

    expect(env.kind).toBe(KIND_PROPOSAL);
    expect(bytesToHex(env.walletFp)).toBe(FIXTURE.fingerprint);
    expect(env.inputs).toHaveLength(1);
    expect(env.outputs).toHaveLength(2);
    expect(env.changeIndex).toBe(1);
    expect(env.changeDerivation).toEqual([1, 0]);
    expect(env.headerAnchors.size).toBe(1);
    expect(env.headerAnchors.get(812345)).toBeInstanceOf(Uint8Array);
    expect(env.outputs[0].scriptHex).toMatch(/^76a914[0-9a-f]{40}88ac$/);
    expect(env.outputs[1].scriptHex).toMatch(/^76a914[0-9a-f]{40}88ac$/);

    // Round-trip through the wire codec.
    const blob = await encodeEnvelope(env);
    const decoded = await decodeEnvelope(blob);
    expect(decoded.kind).toBe(KIND_PROPOSAL);
    if (decoded.kind !== KIND_PROPOSAL) return;
    expect(decoded.inputs[0].txid).toBe("aa".repeat(32));
    expect(decoded.inputs[0].sats).toBe(50_000);
    expect(decoded.outputs.length).toBe(2);
    expect(decoded.outputs[0].sats).toBe(30_000);
    expect(decoded.outputs[1].sats).toBe(19_500);
    expect(decoded.feeRate).toBe(500);
  });

  it("supports 1-input no-change (dust folded into fee)", () => {
    const env = buildUnsignedProposal({
      walletFingerprintHex: FIXTURE.fingerprint,
      inputs: [
        {
          txid: "aa".repeat(32),
          vout: 0,
          sats: 10_000,
          derivation: [0, 0],
          proof: fakeProof(1, 812345),
        },
      ],
      recipientAddress: RECIPIENT,
      recipientSats: 9_700,
      feeRateSatskb: 500,
    });
    expect(env.outputs).toHaveLength(1);
    expect(env.changeIndex).toBe(0); // sentinel value
  });

  it("aggregates header anchors per-height across multiple inputs", () => {
    const env = buildUnsignedProposal({
      walletFingerprintHex: FIXTURE.fingerprint,
      inputs: [
        {
          txid: "aa".repeat(32),
          vout: 0,
          sats: 30_000,
          derivation: [0, 0],
          proof: fakeProof(1, 812345),
        },
        {
          txid: "bb".repeat(32),
          vout: 1,
          sats: 30_000,
          derivation: [0, 1],
          proof: fakeProof(2, 812346),
        },
      ],
      recipientAddress: RECIPIENT,
      recipientSats: 55_000,
      changeAddress: CHANGE,
      changeSats: 4_700,
      changeDerivation: [1, 0],
      feeRateSatskb: 500,
    });
    expect(env.headerAnchors.size).toBe(2);
    expect(env.headerAnchors.has(812345)).toBe(true);
    expect(env.headerAnchors.has(812346)).toBe(true);
  });

  it("rejects conflicting header anchors at the same height", () => {
    expect(() =>
      buildUnsignedProposal({
        walletFingerprintHex: FIXTURE.fingerprint,
        inputs: [
          {
            txid: "aa".repeat(32),
            vout: 0,
            sats: 30_000,
            derivation: [0, 0],
            proof: fakeProof(1, 812345),
          },
          {
            txid: "bb".repeat(32),
            vout: 0,
            sats: 30_000,
            derivation: [0, 1],
            proof: fakeProof(2, 812345), // same height, different seed -> different root
          },
        ],
        recipientAddress: RECIPIENT,
        recipientSats: 55_000,
        feeRateSatskb: 500,
      }),
    ).toThrow(/conflicting header anchors/);
  });

  it("rejects malformed fingerprint", () => {
    expect(() =>
      buildUnsignedProposal({
        walletFingerprintHex: "not-hex",
        inputs: [
          {
            txid: "aa".repeat(32),
            vout: 0,
            sats: 50_000,
            derivation: [0, 0],
            proof: fakeProof(1, 812345),
          },
        ],
        recipientAddress: RECIPIENT,
        recipientSats: 1_000,
        feeRateSatskb: 500,
      }),
    ).toThrow(/walletFingerprintHex/);
  });

  it("rejects an empty input list", () => {
    expect(() =>
      buildUnsignedProposal({
        walletFingerprintHex: FIXTURE.fingerprint,
        inputs: [],
        recipientAddress: RECIPIENT,
        recipientSats: 1_000,
        feeRateSatskb: 500,
      }),
    ).toThrow(ProposalBuilderError);
  });
});

describe("buildUnsignedProposal + coin selection integration", () => {
  it("greedy selection feeds the builder cleanly", async () => {
    const utxos = [
      {
        txid: "aa".repeat(32),
        vout: 0,
        sats: 60_000,
        derivation: [0, 0] as [number, number],
      },
      {
        txid: "bb".repeat(32),
        vout: 1,
        sats: 30_000,
        derivation: [0, 1] as [number, number],
      },
    ];
    const sel = selectUtxosGreedy(utxos, 25_000, 500);
    const env = buildUnsignedProposal({
      walletFingerprintHex: FIXTURE.fingerprint,
      inputs: sel.inputs.map((i, n) => ({
        ...i,
        proof: fakeProof(n + 1, 812345),
      })),
      recipientAddress: RECIPIENT,
      recipientSats: 25_000,
      changeAddress: CHANGE,
      changeSats: sel.changeSats,
      changeDerivation: [1, 0],
      feeRateSatskb: 500,
    });
    expect(env.outputs[0].sats).toBe(25_000);
    expect(env.outputs[1].sats).toBe(sel.changeSats);
    const blob = await encodeEnvelope(env);
    const back = await decodeEnvelope(blob);
    if (back.kind !== KIND_PROPOSAL) throw new Error("kind drift");
    expect(back.inputs).toHaveLength(sel.inputs.length);
  });
});

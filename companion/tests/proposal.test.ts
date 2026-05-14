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
  // ``InputProof.merkleRoot`` is the displayed (big-endian) hex form.
  // The proposal builder reverses it to raw byte order before
  // anchoring — we mirror that convention in tests so anchor lookups
  // line up with the encoded envelope.
  const merkleRoot = Array.from(root)
    .slice()
    .reverse()
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return {
    beef: new Uint8Array(64).map((_, i) => (seed * 7 + i) & 0xff),
    merklePath: new Uint8Array(48).map((_, i) => (seed * 11 + i) & 0xff),
    height,
    merkleRoot,
  };
}

const ANCHOR_HEIGHT = 800_001;

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
          proof: fakeProof(1, ANCHOR_HEIGHT),
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
    const anchorRoot = env.headerAnchors.get(ANCHOR_HEIGHT);
    expect(anchorRoot).toBeInstanceOf(Uint8Array);
    expect(anchorRoot?.byteLength).toBe(32);
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
    expect(decoded.headerAnchors.size).toBe(1);
    expect(decoded.headerAnchors.get(ANCHOR_HEIGHT)).toEqual(anchorRoot);
  });

  it("refuses to build a no-change proposal (v1 spec mandates change)", () => {
    expect(() =>
      buildUnsignedProposal({
        walletFingerprintHex: FIXTURE.fingerprint,
        inputs: [
          {
            txid: "aa".repeat(32),
            vout: 0,
            sats: 10_000,
            derivation: [0, 0],
            proof: fakeProof(1, ANCHOR_HEIGHT),
          },
        ],
        recipientAddress: RECIPIENT,
        recipientSats: 9_700,
        feeRateSatskb: 500,
        // changeAddress / changeSats / changeDerivation deliberately omitted
        // to assert the type / runtime guards reject the call.
      } as unknown as Parameters<typeof buildUnsignedProposal>[0]),
    ).toThrow(ProposalBuilderError);
  });

  it("every built proposal carries an explicit P2PKH change output at changeIndex", () => {
    const env = buildUnsignedProposal({
      walletFingerprintHex: FIXTURE.fingerprint,
      inputs: [
        {
          txid: "aa".repeat(32),
          vout: 0,
          sats: 60_000,
          derivation: [0, 0],
          proof: fakeProof(1, ANCHOR_HEIGHT),
        },
      ],
      recipientAddress: RECIPIENT,
      recipientSats: 50_000,
      changeAddress: CHANGE,
      changeSats: 9_500,
      changeDerivation: [1, 0],
      feeRateSatskb: 500,
    });
    expect(env.outputs.length).toBeGreaterThanOrEqual(2);
    expect(env.changeIndex).toBe(env.outputs.length - 1);
    expect(env.outputs[env.changeIndex].scriptHex).toMatch(
      /^76a914[0-9a-f]{40}88ac$/,
    );
    expect(env.changeDerivation).toEqual([1, 0]);
  });

  it("rejects an input without a confirmed height", () => {
    expect(() =>
      buildUnsignedProposal({
        walletFingerprintHex: FIXTURE.fingerprint,
        inputs: [
          {
            txid: "aa".repeat(32),
            vout: 0,
            sats: 30_000,
            derivation: [0, 0],
            proof: fakeProof(1, 0),
          },
        ],
        recipientAddress: RECIPIENT,
        recipientSats: 25_000,
        changeAddress: CHANGE,
        changeSats: 4_700,
        changeDerivation: [1, 0],
        feeRateSatskb: 500,
      }),
    ).toThrow(/no confirmed height/);
  });

  it("collapses inputs in the same block to a single anchor entry", () => {
    // Two inputs at the same height — the proof's merkleRoot must
    // therefore agree, since a real WoC fetch would return the same
    // header for both. The builder should emit exactly one anchor.
    const env = buildUnsignedProposal({
      walletFingerprintHex: FIXTURE.fingerprint,
      inputs: [
        {
          txid: "aa".repeat(32),
          vout: 0,
          sats: 30_000,
          derivation: [0, 0],
          proof: fakeProof(1, ANCHOR_HEIGHT),
        },
        {
          txid: "bb".repeat(32),
          vout: 1,
          sats: 30_000,
          derivation: [0, 1],
          proof: fakeProof(1, ANCHOR_HEIGHT),
        },
      ],
      recipientAddress: RECIPIENT,
      recipientSats: 50_000,
      changeAddress: CHANGE,
      changeSats: 9_500,
      changeDerivation: [1, 0],
      feeRateSatskb: 500,
    });
    expect(env.headerAnchors.size).toBe(1);
  });

  it("refuses to ship inputs in the same block with disagreeing roots", () => {
    expect(() =>
      buildUnsignedProposal({
        walletFingerprintHex: FIXTURE.fingerprint,
        inputs: [
          {
            txid: "aa".repeat(32),
            vout: 0,
            sats: 30_000,
            derivation: [0, 0],
            proof: fakeProof(1, ANCHOR_HEIGHT),
          },
          {
            txid: "bb".repeat(32),
            vout: 1,
            sats: 30_000,
            derivation: [0, 1],
            // Same height, different seed → different merkle root.
            proof: fakeProof(2, ANCHOR_HEIGHT),
          },
        ],
        recipientAddress: RECIPIENT,
        recipientSats: 50_000,
        changeAddress: CHANGE,
        changeSats: 9_500,
        changeDerivation: [1, 0],
        feeRateSatskb: 500,
      }),
    ).toThrow(/disagree on merkle root/);
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
            proof: fakeProof(1, ANCHOR_HEIGHT),
          },
        ],
        recipientAddress: RECIPIENT,
        recipientSats: 1_000,
        changeAddress: CHANGE,
        changeSats: 48_700,
        changeDerivation: [1, 0],
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
        changeAddress: CHANGE,
        changeSats: 100,
        changeDerivation: [1, 0],
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
        // Different heights per input so each contributes a distinct
        // anchor, exercising the multi-anchor path through the codec.
        proof: fakeProof(n + 1, ANCHOR_HEIGHT + n),
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
    expect(env.headerAnchors.size).toBe(sel.inputs.length);
    const blob = await encodeEnvelope(env);
    const back = await decodeEnvelope(blob);
    if (back.kind !== KIND_PROPOSAL) throw new Error("kind drift");
    expect(back.inputs).toHaveLength(sel.inputs.length);
    expect(back.headerAnchors.size).toBe(sel.inputs.length);
  });
});

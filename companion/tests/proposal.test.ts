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

/**
 * Make a synthetic header chain `[fromHeight..fromHeight+count-1]`
 * suitable for the codec round-trip. The bytes do NOT pass PoW; the
 * proposal builder's contract is to ship whatever headers the caller
 * gives it (the Pi does the validation), so this is the right level
 * to fake at for unit-testing the builder in isolation.
 */
function makeHeaders(count: number): Uint8Array[] {
  const out: Uint8Array[] = [];
  for (let i = 0; i < count; i++) {
    const h = new Uint8Array(80);
    h[0] = 0x01;
    // Bake the index into the merkleroot slot so duplicates are
    // unequal at the byte level.
    h[36] = i & 0xff;
    h[37] = (i >>> 8) & 0xff;
    out.push(h);
  }
  return out;
}

const CHECKPOINT_HEIGHT = 800_000;

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
          proof: fakeProof(1, CHECKPOINT_HEIGHT + 1),
        },
      ],
      recipientAddress: RECIPIENT,
      recipientSats: 30_000,
      changeAddress: CHANGE,
      changeSats: 19_500,
      changeDerivation: [1, 0],
      feeRateSatskb: 500,
      locktime: 0,
      checkpointHeight: CHECKPOINT_HEIGHT,
      headers: makeHeaders(10),
    });

    expect(env.kind).toBe(KIND_PROPOSAL);
    expect(bytesToHex(env.walletFp)).toBe(FIXTURE.fingerprint);
    expect(env.inputs).toHaveLength(1);
    expect(env.outputs).toHaveLength(2);
    expect(env.changeIndex).toBe(1);
    expect(env.changeDerivation).toEqual([1, 0]);
    expect(env.checkpointHeight).toBe(CHECKPOINT_HEIGHT);
    expect(env.headers).toHaveLength(10);
    for (const h of env.headers) expect(h.byteLength).toBe(80);
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
    expect(decoded.checkpointHeight).toBe(CHECKPOINT_HEIGHT);
    expect(decoded.headers).toHaveLength(10);
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
            proof: fakeProof(1, CHECKPOINT_HEIGHT + 1),
          },
        ],
        recipientAddress: RECIPIENT,
        recipientSats: 9_700,
        feeRateSatskb: 500,
        checkpointHeight: CHECKPOINT_HEIGHT,
        headers: makeHeaders(10),
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
          proof: fakeProof(1, CHECKPOINT_HEIGHT + 1),
        },
      ],
      recipientAddress: RECIPIENT,
      recipientSats: 50_000,
      changeAddress: CHANGE,
      changeSats: 9_500,
      changeDerivation: [1, 0],
      feeRateSatskb: 500,
      checkpointHeight: CHECKPOINT_HEIGHT,
      headers: makeHeaders(10),
    });
    expect(env.outputs.length).toBeGreaterThanOrEqual(2);
    expect(env.changeIndex).toBe(env.outputs.length - 1);
    expect(env.outputs[env.changeIndex].scriptHex).toMatch(
      /^76a914[0-9a-f]{40}88ac$/,
    );
    expect(env.changeDerivation).toEqual([1, 0]);
  });

  it("rejects an input whose height is older than the firmware checkpoint", () => {
    expect(() =>
      buildUnsignedProposal({
        walletFingerprintHex: FIXTURE.fingerprint,
        inputs: [
          {
            txid: "aa".repeat(32),
            vout: 0,
            sats: 30_000,
            derivation: [0, 0],
            proof: fakeProof(1, CHECKPOINT_HEIGHT - 5),
          },
        ],
        recipientAddress: RECIPIENT,
        recipientSats: 25_000,
        changeAddress: CHANGE,
        changeSats: 4_700,
        changeDerivation: [1, 0],
        feeRateSatskb: 500,
        checkpointHeight: CHECKPOINT_HEIGHT,
        headers: makeHeaders(10),
      }),
    ).toThrow(/older than the firmware checkpoint/);
  });

  it("rejects an input whose height is past the chain tip we are shipping", () => {
    // Headers cover heights checkpoint+1 .. checkpoint+10; the input
    // claims height checkpoint+999, far past the chain tip.
    expect(() =>
      buildUnsignedProposal({
        walletFingerprintHex: FIXTURE.fingerprint,
        inputs: [
          {
            txid: "aa".repeat(32),
            vout: 0,
            sats: 30_000,
            derivation: [0, 0],
            proof: fakeProof(1, CHECKPOINT_HEIGHT + 999),
          },
        ],
        recipientAddress: RECIPIENT,
        recipientSats: 25_000,
        changeAddress: CHANGE,
        changeSats: 4_700,
        changeDerivation: [1, 0],
        feeRateSatskb: 500,
        checkpointHeight: CHECKPOINT_HEIGHT,
        headers: makeHeaders(10),
      }),
    ).toThrow(/exceeds chain tip/);
  });

  it("rejects an empty headers list", () => {
    expect(() =>
      buildUnsignedProposal({
        walletFingerprintHex: FIXTURE.fingerprint,
        inputs: [
          {
            txid: "aa".repeat(32),
            vout: 0,
            sats: 30_000,
            derivation: [0, 0],
            proof: fakeProof(1, CHECKPOINT_HEIGHT + 1),
          },
        ],
        recipientAddress: RECIPIENT,
        recipientSats: 25_000,
        changeAddress: CHANGE,
        changeSats: 4_700,
        changeDerivation: [1, 0],
        feeRateSatskb: 500,
        checkpointHeight: CHECKPOINT_HEIGHT,
        headers: [],
      }),
    ).toThrow(/headers must be a non-empty list/);
  });

  it("rejects a non-80-byte header in the chain", () => {
    const bad = makeHeaders(3);
    bad[1] = new Uint8Array(79); // wrong length
    expect(() =>
      buildUnsignedProposal({
        walletFingerprintHex: FIXTURE.fingerprint,
        inputs: [
          {
            txid: "aa".repeat(32),
            vout: 0,
            sats: 30_000,
            derivation: [0, 0],
            proof: fakeProof(1, CHECKPOINT_HEIGHT + 1),
          },
        ],
        recipientAddress: RECIPIENT,
        recipientSats: 25_000,
        changeAddress: CHANGE,
        changeSats: 4_700,
        changeDerivation: [1, 0],
        feeRateSatskb: 500,
        checkpointHeight: CHECKPOINT_HEIGHT,
        headers: bad,
      }),
    ).toThrow(/headers\[1\] must be 80 bytes/);
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
            proof: fakeProof(1, CHECKPOINT_HEIGHT + 1),
          },
        ],
        recipientAddress: RECIPIENT,
        recipientSats: 1_000,
        changeAddress: CHANGE,
        changeSats: 48_700,
        changeDerivation: [1, 0],
        feeRateSatskb: 500,
        checkpointHeight: CHECKPOINT_HEIGHT,
        headers: makeHeaders(10),
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
        checkpointHeight: CHECKPOINT_HEIGHT,
        headers: makeHeaders(10),
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
        proof: fakeProof(n + 1, CHECKPOINT_HEIGHT + 1),
      })),
      recipientAddress: RECIPIENT,
      recipientSats: 25_000,
      changeAddress: CHANGE,
      changeSats: sel.changeSats,
      changeDerivation: [1, 0],
      feeRateSatskb: 500,
      checkpointHeight: CHECKPOINT_HEIGHT,
      headers: makeHeaders(10),
    });
    expect(env.outputs[0].sats).toBe(25_000);
    expect(env.outputs[1].sats).toBe(sel.changeSats);
    const blob = await encodeEnvelope(env);
    const back = await decodeEnvelope(blob);
    if (back.kind !== KIND_PROPOSAL) throw new Error("kind drift");
    expect(back.inputs).toHaveLength(sel.inputs.length);
  });
});

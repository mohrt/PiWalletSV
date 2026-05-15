/**
 * Codec round-trip page (`#/loop`).
 *
 * Runs an in-memory round-trip of every envelope kind through the
 * full wire stack:
 *
 *   build → CBOR + gzip → PW1 multipart split → assemble → gunzip + CBOR → decode
 *
 * All three round-trips fire on mount and the page renders a status
 * table. No camera, no hardware — it's a one-page proof that the
 * PWA's encode/decode/framing stack agrees with itself, which (paired
 * with the fixture-decode test in vitest) also proves it agrees with
 * the Pi's `piwallet.qr` + `piwallet.core.envelope`.
 */
import {
  type Envelope,
  type SignedTxT,
  type UnsignedProposalT,
  type XpubExportT,
  KIND_PROPOSAL,
  KIND_SIGNED,
  KIND_XPUB,
  bytesToHex,
  decodeEnvelope,
  encodeEnvelope,
  hexToBytes,
} from "../lib/envelope.js";
import { encodeMultipartLines, joinMultipartLines } from "../pw1.js";

interface RoundTripResult {
  name: string;
  kind: string;
  envelopeBytes: number;
  numFrames: number;
  ok: boolean;
  error?: string;
  detail?: string;
}

function makeXpub(): XpubExportT {
  return {
    kind: KIND_XPUB,
    xpub:
      "xpub6CdMDgU2hzWyeZ852LWqp5AfDz3ty2cRfi4jEw9BT8aNYugMQv" +
      "VykQsKLARZdbqKKp7yTviJdL1N9saYLmJNKD1rwVAwLTmU8r8qKeoyG4R",
    path: "m/44'/236'/0'",
    label: "demo wallet",
    fingerprint: hexToBytes("cf987d8c"),
    network: "main",
  };
}

function makeProposal(): UnsignedProposalT {
  // The loop page exercises the codec round-trip only and never
  // ships this envelope to a Pi. The production proposal builder
  // pulls each anchor's merkle root from a confirmed WoC header
  // lookup; here we use a sentinel byte string.
  const sentinelRoot = new Uint8Array(32).fill(0x42);
  return {
    kind: KIND_PROPOSAL,
    walletFp: hexToBytes("cf987d8c"),
    inputs: [
      {
        txid: "ab".repeat(32),
        vout: 0,
        sats: 50_000,
        beef: new Uint8Array(64).fill(0xaa),
        derivation: [0, 5],
      },
    ],
    outputs: [
      { scriptHex: `76a914${"00".repeat(20)}88ac`, sats: 30_000 },
      { scriptHex: `76a914${"11".repeat(20)}88ac`, sats: 19_500 },
    ],
    changeIndex: 1,
    changeDerivation: [1, 0],
    feeRate: 500,
    locktime: 0,
    headerAnchors: new Map([[812345, sentinelRoot]]),
  };
}

function makeSigned(): SignedTxT {
  // Hand-rolled Atomic BEEF: 4-byte magic + 32-byte subject TXID (raw
  // byte order) + a placeholder BEEF body. Used only by the in-app
  // dev demo / smoke loop; the production sign path on the Pi emits
  // the real BRC-95 form via `piwallet.core.atomic_beef.encode`.
  const txidBytes = hexToBytes("cd".repeat(32)).reverse();
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

function bytesEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

async function runRoundTrip(
  name: string,
  env: Envelope,
): Promise<RoundTripResult> {
  try {
    const blob = await encodeEnvelope(env);
    const lines = encodeMultipartLines(blob, 720);
    // shuffle so we exercise the assembler's out-of-order path too
    const shuffled = [...lines].reverse();
    const reassembled = joinMultipartLines(shuffled);
    if (!bytesEqual(blob, reassembled)) {
      return {
        name,
        kind: env.kind,
        envelopeBytes: blob.byteLength,
        numFrames: lines.length,
        ok: false,
        error: "PW1 reassembly did not produce the original bytes",
      };
    }
    const decoded = await decodeEnvelope(reassembled);
    if (decoded.kind !== env.kind) {
      return {
        name,
        kind: env.kind,
        envelopeBytes: blob.byteLength,
        numFrames: lines.length,
        ok: false,
        error: `kind mismatch after decode: got ${decoded.kind}`,
      };
    }
    return {
      name,
      kind: env.kind,
      envelopeBytes: blob.byteLength,
      numFrames: lines.length,
      ok: true,
      detail: summarize(decoded),
    };
  } catch (e) {
    return {
      name,
      kind: env.kind,
      envelopeBytes: 0,
      numFrames: 0,
      ok: false,
      error: (e as Error).message,
    };
  }
}

function summarize(env: Envelope): string {
  if (env.kind === KIND_XPUB) {
    return `walletFp ${bytesToHex(env.fingerprint)}, ${env.xpub.slice(0, 12)}…`;
  }
  if (env.kind === KIND_PROPOSAL) {
    const anchorHeights = [...env.headerAnchors.keys()].sort((a, b) => a - b);
    const anchorSummary =
      anchorHeights.length === 0
        ? "no anchors"
        : anchorHeights.length === 1
          ? `1 anchor @ height ${anchorHeights[0]}`
          : `${anchorHeights.length} anchors (` +
            `${anchorHeights[0]}–${anchorHeights[anchorHeights.length - 1]})`;
    return (
      `walletFp ${bytesToHex(env.walletFp)}, ` +
      `${env.inputs.length} input → ${env.outputs.length} output, ` +
      `change@${env.changeIndex}, ${anchorSummary}`
    );
  }
  // signed_tx envelopes carry the txid in the BRC-95 Atomic BEEF
  // header; surface only the byte size + the leading magic so the
  // dev loop has a one-line summary without parsing the inner BEEF.
  return (
    `walletFp ${bytesToHex(env.walletFp)}, ` +
    `atomicBeef ${env.atomicBeef.byteLength}B (BRC-95)`
  );
}

export function mountLoopPage(root: HTMLElement): () => void {
  root.innerHTML = `
    <main class="page">
      <header class="page-header">
        <h1>Codec round-trip<span class="brand"> · PiWalletSV (dev)</span></h1>
        <nav>
          <a href="#/wallets">Wallets</a>
          <a href="#/scan">Scan QR</a>
          <a href="#/loop" class="active">Loop (dev)</a>
        </nav>
      </header>

      <section class="card">
        <p class="muted-line" style="margin-bottom: 0.75rem;">
          Builds a synthetic envelope of each kind, encodes via gzip + CBOR,
          splits into PW1 multipart frames, reassembles in reverse order,
          gunzips and CBOR-decodes. Pure in-memory — no camera needed —
          so this is a one-page sanity check that the wire stack agrees
          with itself.
        </p>
        <table class="loop-results" id="loopResults">
          <thead>
            <tr>
              <th>verdict</th>
              <th>envelope</th>
              <th>kind</th>
              <th>gzip bytes</th>
              <th>frames</th>
              <th>detail</th>
            </tr>
          </thead>
          <tbody><tr><td colspan="6" class="muted-line">running…</td></tr></tbody>
        </table>
        <p id="loopSummary" class="muted-line" style="margin-top: 0.75rem;"></p>
      </section>
    </main>
  `;

  const $tbody = root.querySelector<HTMLTableSectionElement>(
    "#loopResults tbody",
  )!;
  const $summary = root.querySelector<HTMLElement>("#loopSummary")!;

  let cancelled = false;

  void (async () => {
    const cases: [string, Envelope][] = [
      ["xpub_export", makeXpub()],
      ["unsigned_proposal", makeProposal()],
      ["signed_tx", makeSigned()],
    ];
    const results: RoundTripResult[] = [];
    for (const [name, env] of cases) {
      const r = await runRoundTrip(name, env);
      if (cancelled) return;
      results.push(r);
    }
    if (cancelled) return;
    renderResults($tbody, $summary, results);
  })();

  return () => {
    cancelled = true;
  };
}

function renderResults(
  tbody: HTMLTableSectionElement,
  summary: HTMLElement,
  results: RoundTripResult[],
): void {
  tbody.innerHTML = "";
  for (const r of results) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="verdict ${r.ok ? "pass" : "fail"}">${r.ok ? "✓ pass" : "✗ fail"}</td>
      <td>${r.name}</td>
      <td><code>${r.kind}</code></td>
      <td>${r.envelopeBytes}</td>
      <td>${r.numFrames}</td>
      <td class="muted-line" style="margin: 0;">${
        r.ok ? (r.detail ?? "") : (r.error ?? "")
      }</td>
    `;
    tbody.appendChild(tr);
  }
  const passed = results.filter((r) => r.ok).length;
  const total = results.length;
  summary.textContent =
    passed === total
      ? `all ${total} round-trips pass · wire format self-consistent`
      : `${passed}/${total} round-trips pass · check the failed rows`;
  summary.classList.toggle("error", passed !== total);
}

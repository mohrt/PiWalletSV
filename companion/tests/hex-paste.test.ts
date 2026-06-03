import { describe, expect, it } from "vitest";

import { decodeHexPasteToBytes, extractHexFromPaste } from "../src/lib/hex-paste.js";

/**
 * Pin the parser's behaviour against the CLI shapes operators are
 * actually likely to paste — bare hex, hex with a `signed_tx:` prefix,
 * hex wrapped at 64 cols, and the full three-line CLI summary that an
 * SSH terminal interleaves onto stdout/stderr.
 */
describe("extractHexFromPaste", () => {
  it("returns bare hex unchanged (the pipeline shape)", () => {
    const r = extractHexFromPaste("1f8b080000");
    expect(r.hex).toBe("1f8b080000");
    expect(r.droppedLabeled).toEqual([]);
    expect(r.droppedOther).toEqual([]);
  });

  it("strips a leading `signed_tx:` label (interactive SSH shape)", () => {
    const r = extractHexFromPaste("signed_tx: 1f8b080000");
    expect(r.hex).toBe("1f8b080000");
    expect(r.droppedLabeled).toEqual([]);
    expect(r.droppedOther).toEqual([]);
  });

  it("uppercases get lower-cased", () => {
    const r = extractHexFromPaste("DEADBEEF");
    expect(r.hex).toBe("deadbeef");
  });

  it("tolerates internal whitespace within a hex line", () => {
    const r = extractHexFromPaste("1f 8b 08 00 00");
    expect(r.hex).toBe("1f8b080000");
  });

  it("concatenates wrapped hex across newlines", () => {
    const wrapped = "1f8b080000\n00000002ff\n65913d8e";
    const r = extractHexFromPaste(wrapped);
    expect(r.hex).toBe("1f8b08000000000002ff65913d8e");
  });

  it("drops the verified+txid summary lines from the full CLI output", () => {
    // Exact shape `piwallet sign` emits on a TTY.
    const sshPaste = [
      "verified: in=99904 out=99791 fee=113",
      "txid: f9c9f9229fdc06499ec5fe196fec185682e6ea03911e347c33d03575682087ed",
      "signed_tx: 1f8b08000000000002ff65913d8e",
    ].join("\n");
    const r = extractHexFromPaste(sshPaste);
    expect(r.hex).toBe("1f8b08000000000002ff65913d8e");
    // Both summary lines are labelled-but-not-hex, so they end up in
    // droppedLabeled (callers can choose to surface a count).
    expect(r.droppedLabeled.length).toBe(2);
    expect(r.droppedOther).toEqual([]);
  });

  it("returns empty hex for empty input", () => {
    expect(extractHexFromPaste("").hex).toBe("");
    expect(extractHexFromPaste("   \n  \n").hex).toBe("");
  });

  it("classifies bare non-hex lines as droppedOther", () => {
    const r = extractHexFromPaste("hello world\n1f8b");
    expect(r.hex).toBe("1f8b");
    expect(r.droppedOther).toEqual(["hello world"]);
    expect(r.droppedLabeled).toEqual([]);
  });

  it("does not strip a `:` that appears mid-hex (no false-positive label match)", () => {
    // Real label prefixes are `[A-Za-z_][A-Za-z0-9_-]*:` at the *start*
    // of the line. A stray `:` in the middle of a line should NOT
    // confuse the parser — it'll just fail the pure-hex test for that
    // line, which is what we want.
    const r = extractHexFromPaste("1f8b:0800");
    expect(r.hex).toBe("");
    expect(r.droppedOther).toEqual(["1f8b:0800"]);
  });

  it("drops unknown labels even when the value is pure hex (txid contamination guard)", () => {
    // A txid is 64 hex chars, so a naive label-strip would happily
    // concatenate it onto the signed_tx hex sitting next to it in the
    // CLI summary. The allow-list is what stops that.
    const r = extractHexFromPaste(
      "txid: f9c9f9229fdc06499ec5fe196fec185682e6ea03911e347c33d03575682087ed",
    );
    expect(r.hex).toBe("");
    expect(r.droppedLabeled.length).toBe(1);
  });

  it("keeps allow-listed payload labels (signed_tx, unsigned_proposal, xpub_export)", () => {
    const cases = ["signed_tx", "unsigned_proposal", "xpub_export", "xpub", "tx"];
    for (const label of cases) {
      const r = extractHexFromPaste(`${label}: deadbeef`);
      expect(r.hex, `label=${label}`).toBe("deadbeef");
    }
  });

  it("drops a label that happens to be hex-shaped if it's unknown", () => {
    // Future-proofing: a hypothetical `env_v1: deadbeef` line is a
    // safety hazard if we accept any label, so the allow-list is
    // strict. Only the known envelope payload labels survive.
    const r = extractHexFromPaste("env_v1: deadbeef");
    expect(r.hex).toBe("");
    expect(r.droppedLabeled).toEqual(["env_v1: deadbeef"]);
  });
});

describe("decodeHexPasteToBytes", () => {
  it("returns bytes for valid pasted hex", () => {
    const r = decodeHexPasteToBytes("signed_tx: 1f8b0800");
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(Array.from(r.bytes)).toEqual([0x1f, 0x8b, 0x08, 0x00]);
    }
  });

  it("surfaces parse errors without throwing", () => {
    const r = decodeHexPasteToBytes("verified: ok");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain("paste an envelope");
  });
});

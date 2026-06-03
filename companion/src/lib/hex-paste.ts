/**
 * Parse hex pasted from a terminal into a clean byte string.
 *
 * Operators using the SSH-paste signing bridge typically copy more than
 * just the hex blob — `piwallet sign` emits three lines on a TTY:
 *
 *     verified: in=99904 out=99791 fee=113
 *     txid: f9c9f9229fdc06...
 *     signed_tx: 1f8b08000000000002ff65913d8e14...
 *
 * (the first two on stderr, the third on stdout, but a terminal session
 * interleaves them.) The naive approach — strip whitespace and require
 * pure hex — rejects this paste because of the `verified:` / `txid:`
 * non-hex content. So we accept multi-line input, drop empty lines,
 * strip an optional `<label>:` prefix per line, then keep only lines
 * that are pure hex after that. The remainder is concatenated and
 * lower-cased.
 *
 * This is intentionally generous in what it accepts (so an operator
 * can copy-paste the entire CLI summary) but strict about what it
 * emits (a contiguous lower-case `[0-9a-f]*` string, validated by
 * the caller before byte-decoding).
 */

const LABEL_PREFIX = /^([A-Za-z_][A-Za-z0-9_-]*):\s*/;
const PURE_HEX = /^[0-9a-f]+$/;

/**
 * Labels the CLI emits whose value is the actual envelope payload
 * (the thing we want to broadcast / decode). Everything else — most
 * notably `txid:` and `verified:` — must be dropped, even if the
 * value happens to look like hex (a txid is 64 hex chars and would
 * otherwise contaminate the signed_tx hex it sits next to in the
 * full CLI summary).
 *
 * Allow-list (not deny-list) is the safer default: a future CLI
 * line we don't know about gets dropped instead of silently merged
 * into the payload.
 */
const PAYLOAD_LABELS: ReadonlySet<string> = new Set([
  "signed_tx",
  "unsigned_proposal",
  "xpub_export",
  "xpub",
  "tx",
]);

export interface HexPasteResult {
  /** Concatenated, whitespace-free, lower-case hex. May be empty. */
  hex: string;
  /** Labelled lines that were dropped (label not in PAYLOAD_LABELS, or
   * value wasn't hex). E.g. "verified: in=99904 …", "txid: f9c9…". */
  droppedLabeled: string[];
  /** Unlabelled lines that didn't parse as hex. */
  droppedOther: string[];
}

export type HexPasteDecodeResult =
  | { ok: true; bytes: Uint8Array; parsed: HexPasteResult }
  | { ok: false; error: string; parsed: HexPasteResult };

/**
 * Scan pasted text and pull out a clean concatenated hex string.
 *
 * Behaviour:
 *  - blank lines are skipped.
 *  - a leading `<label>:` token is parsed; the label is matched
 *    against `PAYLOAD_LABELS`. If unknown (e.g. `txid:`,
 *    `verified:`), the entire line is dropped, regardless of whether
 *    the rest is hex — so the operator can paste the full CLI
 *    summary.
 *  - within a kept line, internal whitespace is removed before the
 *    hex test (so an operator can paste `1f 8b 08 …`).
 *  - lines whose remainder is pure hex are kept.
 *  - all other lines are dropped, with their original text reported
 *    via `droppedLabeled` or `droppedOther` for caller diagnostics.
 */
export function extractHexFromPaste(input: string): HexPasteResult {
  const droppedLabeled: string[] = [];
  const droppedOther: string[] = [];
  const pieces: string[] = [];
  for (const raw of input.split(/\r?\n/)) {
    const trimmed = raw.trim();
    if (trimmed.length === 0) continue;
    const labelMatch = LABEL_PREFIX.exec(trimmed);
    let candidate: string;
    let hadLabel: boolean;
    if (labelMatch !== null) {
      hadLabel = true;
      const label = labelMatch[1].toLowerCase();
      if (!PAYLOAD_LABELS.has(label)) {
        // Unknown label (txid:, verified:, error:, …). Drop the whole
        // line so its hex-shaped value can't contaminate the payload.
        droppedLabeled.push(trimmed);
        continue;
      }
      candidate = trimmed.slice(labelMatch[0].length);
    } else {
      hadLabel = false;
      candidate = trimmed;
    }
    const compact = candidate.replace(/\s+/g, "").toLowerCase();
    if (compact.length === 0) {
      (hadLabel ? droppedLabeled : droppedOther).push(trimmed);
      continue;
    }
    if (!PURE_HEX.test(compact)) {
      (hadLabel ? droppedLabeled : droppedOther).push(trimmed);
      continue;
    }
    pieces.push(compact);
  }
  return {
    hex: pieces.join(""),
    droppedLabeled,
    droppedOther,
  };
}

/** Parse pasted CLI / terminal text into envelope bytes. */
export function decodeHexPasteToBytes(input: string): HexPasteDecodeResult {
  const parsed = extractHexFromPaste(input);
  const cleaned = parsed.hex;
  if (cleaned.length === 0) {
    return { ok: false, error: "paste an envelope hex string first", parsed };
  }
  if (cleaned.length % 2 !== 0) {
    return {
      ok: false,
      error: `hex has odd length ${cleaned.length}; check the paste was complete`,
      parsed,
    };
  }
  if (!PURE_HEX.test(cleaned)) {
    return {
      ok: false,
      error: "hex contains non-[0-9a-f] characters after stripping whitespace",
      parsed,
    };
  }
  try {
    const bytes = new Uint8Array(cleaned.length / 2);
    for (let i = 0; i < bytes.length; i++) {
      bytes[i] = parseInt(cleaned.slice(i * 2, i * 2 + 2), 16);
    }
    return { ok: true, bytes, parsed };
  } catch (e) {
    return {
      ok: false,
      error: `hex decode failed: ${(e as Error).message}`,
      parsed,
    };
  }
}

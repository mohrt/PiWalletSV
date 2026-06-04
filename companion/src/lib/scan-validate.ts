/**
 * Per-workflow QR / scan result validation.
 * Each screen accepts only the payload type it expects; wrong types are rejected
 * with a user-facing message so the scanner can keep running.
 */
import {
  decodeEnvelope,
  KIND_PROPOSAL,
  KIND_SIGNED,
  KIND_XPUB,
  type Envelope,
  type XpubExportT,
} from "./envelope.js";
import { WalletStoreError } from "./wallets.js";
import { walletBackupBytesToJson, validateWalletBackupJson } from "./wallet-backup.js";

export type ScanWorkflow =
  | "pair-xpub"
  | "send-signed-tx"
  | "send-address"
  | "settings-backup";

export type ValidatedPw1Result =
  | { workflow: "pair-xpub"; envelope: XpubExportT; bytes: Uint8Array }
  | { workflow: "send-signed-tx"; envelope: Extract<Envelope, { kind: typeof KIND_SIGNED }>; bytes: Uint8Array }
  | { workflow: "settings-backup"; json: string; bytes: Uint8Array };

export type ScanValidation =
  | { ok: true; result: ValidatedPw1Result | { workflow: "send-address"; address: string } }
  | { ok: false; message: string };

const WORKFLOW_HINT: Record<ScanWorkflow, string> = {
  "pair-xpub":
    "this screen expects a pairing xpub QR from the Pi (Add wallet flow)",
  "send-signed-tx":
    "this screen expects the signed transaction QR from the Pi (Send → Step 2)",
  "send-address": "this screen expects a plain BSV payment address QR",
  "settings-backup":
    "this screen expects a wallet transfer QR from Settings on another phone",
};

function wrongKindMessage(workflow: ScanWorkflow, kind: string | null): string {
  const hint = WORKFLOW_HINT[workflow];
  if (kind === KIND_SIGNED) {
    return `Wrong QR — signed transaction detected. Open Wallets → your wallet → Send → Step 2. (${hint})`;
  }
  if (kind === KIND_PROPOSAL) {
    return `Wrong QR — unsigned send proposal detected. Complete the send on the Pi from Send → Step 1. (${hint})`;
  }
  if (kind === KIND_XPUB) {
    return `Wrong QR — pairing xpub detected. Use + Add wallet to pair. (${hint})`;
  }
  return `Wrong QR — not a valid PiWallet payload for this step. (${hint})`;
}

/** Validate a reassembled PW1 byte payload for a specific workflow. */
export async function validatePw1Bytes(
  workflow: ScanWorkflow,
  bytes: Uint8Array,
): Promise<ScanValidation> {
  if (workflow === "settings-backup") {
    let json: string;
    try {
      json = walletBackupBytesToJson(bytes);
    } catch (e) {
      return {
        ok: false,
        message:
          `Wrong QR — not a wallet backup transfer. ${WORKFLOW_HINT["settings-backup"]}.`,
      };
    }
    try {
      validateWalletBackupJson(json);
    } catch (e) {
      const msg = e instanceof WalletStoreError ? e.message : (e as Error).message;
      return { ok: false, message: `Wrong QR — invalid backup: ${msg}` };
    }
    return { ok: true, result: { workflow: "settings-backup", json, bytes } };
  }

  let env: Envelope;
  try {
    env = await decodeEnvelope(bytes);
  } catch {
    return { ok: false, message: wrongKindMessage(workflow, null) };
  }

  if (workflow === "pair-xpub") {
    if (env.kind !== KIND_XPUB) {
      return { ok: false, message: wrongKindMessage(workflow, env.kind) };
    }
    return { ok: true, result: { workflow: "pair-xpub", envelope: env, bytes } };
  }

  if (workflow === "send-signed-tx") {
    if (env.kind !== KIND_SIGNED) {
      return { ok: false, message: wrongKindMessage(workflow, env.kind) };
    }
    return { ok: true, result: { workflow: "send-signed-tx", envelope: env, bytes } };
  }

  return { ok: false, message: wrongKindMessage(workflow, env.kind) };
}

/** Validate a single-frame address QR (Send recipient field). */
export function validateAddressQr(raw: string): ScanValidation {
  const trimmed = raw.trim();
  if (!trimmed) {
    return { ok: false, message: "Empty QR code." };
  }
  if (trimmed.startsWith("PW1|")) {
    return {
      ok: false,
      message:
        "Wrong QR — PiWallet multipart QR detected. Use + Add wallet or Send → Step 2 for those codes.",
    };
  }
  const addr = trimmed.replace(/^bitcoin:/i, "").split("?")[0].trim();
  if (!addr) {
    return { ok: false, message: "Wrong QR — no address found." };
  }
  if (!/^[13mn][a-km-zA-HJ-NP-Z1-9]{20,}$/.test(addr)) {
    return {
      ok: false,
      message: "Wrong QR — does not look like a BSV address (expected 1…, m…, or n…).",
    };
  }
  return { ok: true, result: { workflow: "send-address", address: addr } };
}

/**
 * Export / import paired-wallet metadata for device migration.
 *
 * Contains only public pairing fields (xpub, label, fingerprint, path) —
 * never seed phrases, PINs, or private keys.
 */
import type { NetworkT } from "./envelope.js";
import { bytesToHex } from "./envelope.js";
import { DerivationError, xpubFingerprint } from "./derive.js";
import {
  WalletStoreError,
  _clearAllWallets,
  addWallet,
  findByFingerprintAndPath,
  listWallets,
  setNextReceiveIndex,
  type WalletRecord,
} from "./wallets.js";
import { encodeMultipartLines } from "../pw1.js";

export const BACKUP_FORMAT = "piwallet-companion-wallets" as const;
export const BACKUP_VERSION = 1;

export interface WalletBackupEntry {
  label: string;
  xpub: string;
  fingerprint: string;
  path: string;
  network?: NetworkT;
  addedAt: string;
  nextReceiveIndex?: number;
}

export interface WalletBackupFile {
  format: typeof BACKUP_FORMAT;
  version: typeof BACKUP_VERSION;
  exportedAt: string;
  wallets: WalletBackupEntry[];
}

export interface ImportWalletResult {
  imported: number;
  skippedDuplicates: number;
  failed: { label: string; reason: string }[];
}

/** Merge skips duplicate pairs; replace clears the local store first. */
export type ImportWalletMode = "merge" | "replace";

export interface ImportWalletOptions {
  mode?: ImportWalletMode;
}

function toBackupEntry(rec: WalletRecord): WalletBackupEntry {
  return {
    label: rec.label,
    xpub: rec.xpub,
    fingerprint: rec.fingerprint,
    path: rec.path,
    network: rec.network ?? "main",
    addedAt: rec.addedAt,
    ...(rec.nextReceiveIndex !== undefined
      ? { nextReceiveIndex: rec.nextReceiveIndex }
      : {}),
  };
}

export async function buildWalletBackupFile(): Promise<WalletBackupFile> {
  const wallets = await listWallets();
  return {
    format: BACKUP_FORMAT,
    version: BACKUP_VERSION,
    exportedAt: new Date().toISOString(),
    wallets: wallets.map(toBackupEntry),
  };
}

export function serializeWalletBackup(file: WalletBackupFile): string {
  return JSON.stringify(file, null, 2);
}

export function walletBackupToBytes(json: string): Uint8Array {
  return new TextEncoder().encode(json);
}

export function walletBackupBytesToJson(bytes: Uint8Array): string {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch (e) {
    throw new WalletStoreError(
      `backup bytes are not valid UTF-8: ${e instanceof Error ? e.message : String(e)}`,
    );
  }
}

export function walletBackupJsonToPw1Lines(json: string): string[] {
  return encodeMultipartLines(walletBackupToBytes(json));
}

export async function buildWalletBackupPw1Lines(): Promise<{
  json: string;
  lines: string[];
  walletCount: number;
}> {
  const file = await buildWalletBackupFile();
  const json = serializeWalletBackup(file);
  return {
    json,
    lines: walletBackupJsonToPw1Lines(json),
    walletCount: file.wallets.length,
  };
}

export function formatImportWalletResult(result: ImportWalletResult): string {
  const parts: string[] = [];
  if (result.imported > 0) {
    parts.push(
      `imported ${result.imported} wallet${result.imported === 1 ? "" : "s"}`,
    );
  }
  if (result.skippedDuplicates > 0) {
    parts.push(
      `skipped ${result.skippedDuplicates} duplicate${result.skippedDuplicates === 1 ? "" : "s"}`,
    );
  }
  if (result.failed.length > 0) {
    parts.push(
      `${result.failed.length} failed (${result.failed.map((f) => f.label).join(", ")})`,
    );
  }
  return parts.length > 0 ? parts.join("; ") + "." : "Nothing to import.";
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function parseBackupFile(raw: string): WalletBackupFile {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (e) {
    throw new WalletStoreError(
      `invalid JSON: ${e instanceof Error ? e.message : String(e)}`,
    );
  }
  if (!isRecord(parsed)) {
    throw new WalletStoreError("backup file must be a JSON object");
  }
  if (parsed.format !== BACKUP_FORMAT) {
    throw new WalletStoreError(
      `unsupported backup format: ${String(parsed.format)}`,
    );
  }
  if (parsed.version !== BACKUP_VERSION) {
    throw new WalletStoreError(
      `unsupported backup version: ${String(parsed.version)}`,
    );
  }
  if (!Array.isArray(parsed.wallets)) {
    throw new WalletStoreError("backup file missing wallets array");
  }
  return {
    format: BACKUP_FORMAT,
    version: BACKUP_VERSION,
    exportedAt: String(parsed.exportedAt ?? ""),
    wallets: parsed.wallets as WalletBackupEntry[],
  };
}

function validateEntry(entry: unknown, index: number): WalletBackupEntry {
  if (!isRecord(entry)) {
    throw new WalletStoreError(`wallets[${index}] must be an object`);
  }
  const label = entry.label;
  const xpub = entry.xpub;
  const fingerprint = entry.fingerprint;
  const path = entry.path;
  const addedAt = entry.addedAt;
  if (typeof label !== "string" || !label.trim()) {
    throw new WalletStoreError(`wallets[${index}].label must be a non-empty string`);
  }
  if (typeof xpub !== "string" || !xpub.trim()) {
    throw new WalletStoreError(`wallets[${index}].xpub must be a string`);
  }
  if (typeof fingerprint !== "string" || !/^[0-9a-fA-F]{8}$/.test(fingerprint)) {
    throw new WalletStoreError(
      `wallets[${index}].fingerprint must be 8 hex chars`,
    );
  }
  if (typeof path !== "string" || !path.startsWith("m/")) {
    throw new WalletStoreError(`wallets[${index}].path must be a derivation path`);
  }
  if (typeof addedAt !== "string" || Number.isNaN(Date.parse(addedAt))) {
    throw new WalletStoreError(`wallets[${index}].addedAt must be an ISO timestamp`);
  }
  let network: NetworkT | undefined;
  if (entry.network !== undefined) {
    if (entry.network !== "main" && entry.network !== "test") {
      throw new WalletStoreError(
        `wallets[${index}].network must be "main" or "test"`,
      );
    }
    network = entry.network;
  }
  let nextReceiveIndex: number | undefined;
  if (entry.nextReceiveIndex !== undefined) {
    if (
      !Number.isInteger(entry.nextReceiveIndex) ||
      (entry.nextReceiveIndex as number) < 0
    ) {
      throw new WalletStoreError(
        `wallets[${index}].nextReceiveIndex must be a non-negative integer`,
      );
    }
    nextReceiveIndex = entry.nextReceiveIndex as number;
  }
  const trimmedXpub = xpub.trim();
  if (!trimmedXpub.startsWith("xpub") && !trimmedXpub.startsWith("tpub")) {
    throw new WalletStoreError(
      `wallets[${index}].xpub must start with xpub or tpub`,
    );
  }
  return {
    label: label.trim(),
    xpub: trimmedXpub,
    fingerprint: fingerprint.toLowerCase(),
    path,
    network,
    addedAt,
    ...(nextReceiveIndex !== undefined ? { nextReceiveIndex } : {}),
  };
}

async function importOneEntry(entry: WalletBackupEntry): Promise<
  "imported" | "skipped"
> {
  let fp: Uint8Array;
  try {
    fp = xpubFingerprint(entry.xpub);
  } catch (e) {
    const msg = e instanceof DerivationError ? e.message : (e as Error).message;
    throw new WalletStoreError(`invalid xpub: ${msg}`);
  }
  const fpHex = bytesToHex(fp);
  if (fpHex !== entry.fingerprint.toLowerCase()) {
    throw new WalletStoreError(
      `fingerprint mismatch (xpub computes ${fpHex}, file has ${entry.fingerprint})`,
    );
  }

  const network: NetworkT = entry.network ?? "main";
  const existing = await findByFingerprintAndPath(fpHex, entry.path);
  if (existing && (existing.network ?? "main") === network) {
    return "skipped";
  }

  const rec = await addWallet({
    label: entry.label,
    xpub: entry.xpub,
    fingerprint: fpHex,
    path: entry.path,
    network,
  });
  if (entry.nextReceiveIndex !== undefined) {
    await setNextReceiveIndex(rec.id, entry.nextReceiveIndex);
  }
  return "imported";
}

export async function importWalletBackup(
  raw: string,
  opts: ImportWalletOptions = {},
): Promise<ImportWalletResult> {
  const mode = opts.mode ?? "merge";
  if (mode === "replace") {
    await _clearAllWallets();
  }
  const file = parseBackupFile(raw);
  const result: ImportWalletResult = {
    imported: 0,
    skippedDuplicates: 0,
    failed: [],
  };

  for (let i = 0; i < file.wallets.length; i++) {
    let entry: WalletBackupEntry;
    try {
      entry = validateEntry(file.wallets[i], i);
    } catch (e) {
      const msg = e instanceof WalletStoreError ? e.message : (e as Error).message;
      result.failed.push({ label: `(entry ${i + 1})`, reason: msg });
      continue;
    }

    try {
      const outcome = await importOneEntry(entry);
      if (outcome === "imported") result.imported += 1;
      else result.skippedDuplicates += 1;
    } catch (e) {
      const msg = e instanceof WalletStoreError ? e.message : (e as Error).message;
      result.failed.push({ label: entry.label, reason: msg });
    }
  }

  return result;
}

export async function importWalletBackupBytes(
  bytes: Uint8Array,
  opts: ImportWalletOptions = {},
): Promise<ImportWalletResult> {
  const json = walletBackupBytesToJson(bytes);
  return importWalletBackup(json, opts);
}

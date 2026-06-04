/**
 * Export / import paired-wallet metadata and companion preferences for migration.
 *
 * Contains public pairing fields (xpub, label, fingerprint, path), cached
 * balance/history snapshots, and local UI settings — never seed phrases,
 * Pi PINs, or private keys (the companion never stores those).
 */
import type { NetworkT } from "./envelope.js";
import { bytesToHex } from "./envelope.js";
import { DerivationError, xpubFingerprint } from "./derive.js";
import {
  type CompanionSettingsBackup,
  applyCompanionSettings,
  exportCompanionSettings,
  validateCompanionSettingsBackup,
} from "./companion-settings.js";
import type { HistorySnapshot } from "./history.js";
import {
  WalletStoreError,
  _clearAllWallets,
  addWallet,
  findByFingerprintAndPath,
  listWallets,
  setDisplayUnit,
  setLastHistory,
  setLastScan,
  setNextReceiveIndex,
  type WalletRecord,
  type WalletScanSnapshot,
} from "./wallets.js";
import { encodeMultipartLines } from "../pw1.js";
import {
  APP_VERSION,
  BACKUP_FORMAT_VERSION,
} from "./version.js";

export { BACKUP_VERSION } from "./version.js";

export const BACKUP_FORMAT = "piwallet-companion-wallets" as const;

export const BACKUP_NEWER_THAN_APP_MSG =
  "Backup was created by a newer companion — update this app and try again.";

export interface WalletBackupEntry {
  label: string;
  xpub: string;
  fingerprint: string;
  path: string;
  network?: NetworkT;
  addedAt: string;
  nextReceiveIndex?: number;
  displayUnit?: "sats" | "bsv" | "fiat";
  lastScan?: WalletScanSnapshot;
  lastHistory?: HistorySnapshot;
}

export interface WalletBackupFile {
  format: typeof BACKUP_FORMAT;
  /** Integer schema tag derived from {@link APP_VERSION} at export time. */
  version: number;
  /** Companion semver that created this backup (informational). */
  companionVersion: string;
  exportedAt: string;
  wallets: WalletBackupEntry[];
  settings?: CompanionSettingsBackup;
}

export interface ImportWalletResult {
  imported: number;
  skippedDuplicates: number;
  failed: { label: string; reason: string }[];
  settingsRestored: boolean;
}

/** Merge skips duplicate pairs; replace clears the local store first. */
export type ImportWalletMode = "merge" | "replace";

/** Wallets-only omits global settings and per-wallet cached snapshots. */
export type BackupExportScope = "wallets-only" | "wallets-and-settings";

export interface BuildWalletBackupOptions {
  scope?: BackupExportScope;
}

export interface ImportWalletOptions {
  mode?: ImportWalletMode;
}

function toBackupEntry(
  rec: WalletRecord,
  scope: BackupExportScope,
): WalletBackupEntry {
  const entry: WalletBackupEntry = {
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
  if (scope === "wallets-and-settings") {
    if (rec.displayUnit !== undefined) entry.displayUnit = rec.displayUnit;
    if (rec.lastScan !== undefined) entry.lastScan = rec.lastScan;
    if (rec.lastHistory !== undefined) entry.lastHistory = rec.lastHistory;
  }
  return entry;
}

export async function buildWalletBackupFile(
  opts: BuildWalletBackupOptions = {},
): Promise<WalletBackupFile> {
  const scope = opts.scope ?? "wallets-and-settings";
  const wallets = await listWallets();
  const file: WalletBackupFile = {
    format: BACKUP_FORMAT,
    version: BACKUP_FORMAT_VERSION,
    companionVersion: APP_VERSION,
    exportedAt: new Date().toISOString(),
    wallets: wallets.map((w) => toBackupEntry(w, scope)),
  };
  if (scope === "wallets-and-settings") {
    file.settings = exportCompanionSettings();
  }
  return file;
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

export async function buildWalletBackupPw1Lines(
  opts: BuildWalletBackupOptions = {},
): Promise<{
  json: string;
  lines: string[];
  walletCount: number;
}> {
  const file = await buildWalletBackupFile(opts);
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
  if (result.settingsRestored) {
    parts.push("restored settings");
  }
  if (result.failed.length > 0) {
    parts.push(
      `${result.failed.length} failed (${result.failed.map((f) => f.label).join(", ")})`,
    );
  }
  return parts.length > 0 ? parts.join("; ") + "." : "Nothing to import.";
}

/** Parse backup JSON without importing — for scan validation. */
export function validateWalletBackupJson(raw: string): void {
  parseBackupFile(raw);
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
  const version = parsed.version;
  if (typeof version !== "number" || !Number.isInteger(version)) {
    throw new WalletStoreError(
      `unsupported backup version: ${String(version)}`,
    );
  }
  if (version < 1) {
    throw new WalletStoreError(
      `unsupported backup version: ${String(version)}`,
    );
  }
  if (version > BACKUP_FORMAT_VERSION) {
    throw new WalletStoreError(BACKUP_NEWER_THAN_APP_MSG);
  }
  if (!Array.isArray(parsed.wallets)) {
    throw new WalletStoreError("backup file missing wallets array");
  }

  let settings: CompanionSettingsBackup | undefined;
  if (parsed.settings !== undefined) {
    try {
      settings = validateCompanionSettingsBackup(parsed.settings);
    } catch (e) {
      throw new WalletStoreError(
        e instanceof Error ? e.message : String(e),
      );
    }
  }

  const companionVersion =
    typeof parsed.companionVersion === "string"
      ? parsed.companionVersion
      : undefined;

  return {
    format: BACKUP_FORMAT,
    version,
    companionVersion: companionVersion ?? "",
    exportedAt: String(parsed.exportedAt ?? ""),
    wallets: parsed.wallets as WalletBackupEntry[],
    settings,
  };
}

function validateScanSnapshot(raw: unknown, index: number): WalletScanSnapshot {
  if (!isRecord(raw)) {
    throw new WalletStoreError(`wallets[${index}].lastScan must be an object`);
  }
  if (typeof raw.at !== "string" || Number.isNaN(Date.parse(raw.at))) {
    throw new WalletStoreError(`wallets[${index}].lastScan.at invalid`);
  }
  if (typeof raw.totalSats !== "number" || !Number.isFinite(raw.totalSats)) {
    throw new WalletStoreError(`wallets[${index}].lastScan.totalSats invalid`);
  }
  if (!Array.isArray(raw.utxos)) {
    throw new WalletStoreError(`wallets[${index}].lastScan.utxos must be array`);
  }
  if (
    typeof raw.lastReceiveUsed !== "number" ||
    typeof raw.lastChangeUsed !== "number" ||
    typeof raw.addressesScanned !== "number"
  ) {
    throw new WalletStoreError(`wallets[${index}].lastScan fields invalid`);
  }
  let stoppedAt: WalletScanSnapshot["stoppedAt"];
  if (raw.stoppedAt !== undefined) {
    if (!isRecord(raw.stoppedAt)) {
      throw new WalletStoreError(`wallets[${index}].lastScan.stoppedAt invalid`);
    }
    if (
      typeof raw.stoppedAt.receive !== "number" ||
      typeof raw.stoppedAt.change !== "number"
    ) {
      throw new WalletStoreError(`wallets[${index}].lastScan.stoppedAt invalid`);
    }
    stoppedAt = {
      receive: raw.stoppedAt.receive,
      change: raw.stoppedAt.change,
    };
  }
  return {
    at: raw.at,
    totalSats: raw.totalSats,
    utxos: raw.utxos as WalletScanSnapshot["utxos"],
    lastReceiveUsed: raw.lastReceiveUsed,
    lastChangeUsed: raw.lastChangeUsed,
    addressesScanned: raw.addressesScanned,
    ...(stoppedAt !== undefined ? { stoppedAt } : {}),
  };
}

function validateHistorySnapshot(raw: unknown, index: number): HistorySnapshot {
  if (!isRecord(raw)) {
    throw new WalletStoreError(`wallets[${index}].lastHistory must be an object`);
  }
  if (typeof raw.at !== "string" || Number.isNaN(Date.parse(raw.at))) {
    throw new WalletStoreError(`wallets[${index}].lastHistory.at invalid`);
  }
  if (!Array.isArray(raw.entries)) {
    throw new WalletStoreError(`wallets[${index}].lastHistory.entries invalid`);
  }
  if (typeof raw.addressesQueried !== "number") {
    throw new WalletStoreError(
      `wallets[${index}].lastHistory.addressesQueried invalid`,
    );
  }
  return {
    at: raw.at,
    entries: raw.entries as HistorySnapshot["entries"],
    addressesQueried: raw.addressesQueried,
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
  let displayUnit: WalletBackupEntry["displayUnit"];
  if (entry.displayUnit !== undefined) {
    if (
      entry.displayUnit !== "sats" &&
      entry.displayUnit !== "bsv" &&
      entry.displayUnit !== "fiat"
    ) {
      throw new WalletStoreError(`wallets[${index}].displayUnit invalid`);
    }
    displayUnit = entry.displayUnit;
  }
  let lastScan: WalletScanSnapshot | undefined;
  if (entry.lastScan !== undefined) {
    lastScan = validateScanSnapshot(entry.lastScan, index);
  }
  let lastHistory: HistorySnapshot | undefined;
  if (entry.lastHistory !== undefined) {
    lastHistory = validateHistorySnapshot(entry.lastHistory, index);
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
    ...(displayUnit !== undefined ? { displayUnit } : {}),
    ...(lastScan !== undefined ? { lastScan } : {}),
    ...(lastHistory !== undefined ? { lastHistory } : {}),
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
  if (entry.displayUnit !== undefined) {
    await setDisplayUnit(rec.id, entry.displayUnit);
  }
  if (entry.lastScan !== undefined) {
    await setLastScan(rec.id, entry.lastScan);
  }
  if (entry.lastHistory !== undefined) {
    await setLastHistory(rec.id, entry.lastHistory);
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
    settingsRestored: false,
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

  if (file.settings) {
    applyCompanionSettings(file.settings);
    result.settingsRestored = true;
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

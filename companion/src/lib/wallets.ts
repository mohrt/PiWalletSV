/**
 * Browser-local IndexedDB store for paired wallets.
 *
 * The companion PWA never stores any signing key; only public metadata
 * (`label`, `xpub`, `fingerprint`, `path`, `addedAt`) is persisted so the
 * UI can list paired wallets, derive receiving addresses, and address
 * outgoing proposals to the right Pi-side signer.
 *
 * Schema is forward-compatible: every record carries a `schemaVersion`,
 * which lets the loader migrate or refuse rows from a newer client.
 */

import type { NetworkT } from "./envelope.js";
import type { WalletUtxo } from "./utxo.js";
import type { HistorySnapshot } from "./history.js";

const DB_NAME = "piwallet-companion";
const DB_VERSION = 1;
const STORE = "wallets";

export const WALLET_SCHEMA_VERSION = 2;

export interface WalletRecord {
  /** UUIDv4 generated on save. */
  id: string;
  /** Human-readable label. Editable by the user; defaults to the Pi label. */
  label: string;
  /** Account-level extended public key (BIP44 m/44'/236'/0'). */
  xpub: string;
  /** 4-byte self-fingerprint, hex. Stable identity for the wallet. */
  fingerprint: string;
  /** Derivation path the Pi declared (`m/44'/236'/0'` for v1). */
  path: string;
  /** ISO 8601 timestamp the user paired this wallet. */
  addedAt: string;
  /** Schema version of this record, for forward-compat migration. */
  schemaVersion: number;
  /**
   * Next-unused receive (m/0/i) index. Mutated when the user marks an
   * address as "used" or when an outgoing proposal consumes one. Older
   * records (v1) lack this field; readers default to 0.
   */
  nextReceiveIndex?: number;
  /**
   * Cached UTXO snapshot from the last `scanWalletUtxos` run. Optional;
   * the wallet works without it (the UI just shows "not scanned yet").
   */
  lastScan?: WalletScanSnapshot;
  /**
   * Wallet's network (`"main"` / `"test"`). Pre-v1.1 records lack
   * this field; readers default to `"main"` because that's the only
   * network the companion supported before testnet shipped, and
   * existing pairings would have stored mainnet addresses regardless.
   */
  network?: NetworkT;
  /**
   * Cached transaction history from the last Bitails fetch (schema v2+).
   * Optional; the wallet works without it (History tab shows "not fetched").
   */
  lastHistory?: HistorySnapshot;
  /**
   * User's preferred display unit: "sats" or "fiat".
   * Persisted so the toggle survives page reloads.
   */
  displayUnit?: "sats" | "bsv" | "fiat";
}

/** Cached output of the gap-limit UTXO scan, persisted per wallet. */
export interface WalletScanSnapshot {
  /** ISO 8601 timestamp the scan completed. */
  at: string;
  /** Sum of `sats` across `utxos`. */
  totalSats: number;
  /** Snapshot of every unspent output discovered by the scan. */
  utxos: WalletUtxo[];
  /** Highest receive index that produced a UTXO (-1 if none). */
  lastReceiveUsed: number;
  /** Highest change index that produced a UTXO (-1 if none). */
  lastChangeUsed: number;
  /** Total addresses probed across both branches. */
  addressesScanned: number;
}

/** Helper that fills in defaults for fields added after schema v1. */
export function withDefaults(rec: WalletRecord): WalletRecord & {
  nextReceiveIndex: number;
  network: NetworkT;
} {
  return {
    ...rec,
    nextReceiveIndex: rec.nextReceiveIndex ?? 0,
    network: rec.network ?? "main",
  };
}

export class WalletStoreError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WalletStoreError";
  }
}

function asWalletStoreError(e: unknown, ctx: string): WalletStoreError {
  const msg = e instanceof Error ? e.message : String(e);
  return new WalletStoreError(`${ctx}: ${msg}`);
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        const store = db.createObjectStore(STORE, { keyPath: "id" });
        store.createIndex("fingerprint", "fingerprint", { unique: false });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () =>
      reject(asWalletStoreError(req.error, "indexedDB.open"));
    req.onblocked = () =>
      reject(new WalletStoreError("indexedDB.open: blocked by another tab"));
  });
}

function txPromise<T>(
  request: IDBRequest<T>,
  ctx: string,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(asWalletStoreError(request.error, ctx));
  });
}

async function withStore<T>(
  mode: IDBTransactionMode,
  fn: (store: IDBObjectStore) => Promise<T> | T,
): Promise<T> {
  const db = await openDb();
  try {
    const tx = db.transaction(STORE, mode);
    const store = tx.objectStore(STORE);
    const result = await Promise.resolve(fn(store));
    return new Promise<T>((resolve, reject) => {
      tx.oncomplete = () => resolve(result);
      tx.onerror = () => reject(asWalletStoreError(tx.error, "transaction"));
      tx.onabort = () => reject(asWalletStoreError(tx.error, "transaction aborted"));
    });
  } finally {
    db.close();
  }
}

function uuid(): string {
  // Browsers / Node 19+ both expose `crypto.randomUUID()`. Falls back to a
  // hash-based assembly only if some embedded runtime lacks it.
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex: string[] = [];
  for (const b of bytes) hex.push(b.toString(16).padStart(2, "0"));
  return (
    `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-` +
    `${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10, 16).join("")}`
  );
}

export interface AddWalletInput {
  label: string;
  xpub: string;
  fingerprint: string;
  path: string;
  /** Optional; defaults to `"main"` for callers predating testnet support. */
  network?: NetworkT;
}

/**
 * Insert a new wallet record. Rejects if a wallet with the same
 * fingerprint+path already exists on the same network, surfacing
 * `WalletStoreError("duplicate-pair")` so the UI can offer to update
 * the existing label rather than silently insert a near-twin. Two
 * wallets that share fingerprint+path but differ in network are
 * accepted as distinct entries (a seed can drive both mainnet and
 * testnet wallets in parallel).
 */
export async function addWallet(input: AddWalletInput): Promise<WalletRecord> {
  const fp = input.fingerprint.toLowerCase();
  const network: NetworkT = input.network ?? "main";
  const dup = await findByFingerprintAndPath(fp, input.path);
  if (dup && (dup.network ?? "main") === network) {
    throw new WalletStoreError(
      `duplicate-pair: a wallet with fingerprint ${fp} on ${input.path} (${network}) is already paired (label: ${dup.label})`,
    );
  }
  const rec: WalletRecord = {
    id: uuid(),
    label: input.label,
    xpub: input.xpub,
    fingerprint: fp,
    path: input.path,
    addedAt: new Date().toISOString(),
    schemaVersion: WALLET_SCHEMA_VERSION,
    network,
  };
  await withStore("readwrite", (store) => txPromise(store.add(rec), "add"));
  return rec;
}

export async function listWallets(): Promise<WalletRecord[]> {
  const out = await withStore("readonly", (store) =>
    txPromise<WalletRecord[]>(
      store.getAll() as IDBRequest<WalletRecord[]>,
      "getAll",
    ),
  );
  // Stable order: newest first.
  return out.sort((a, b) => (a.addedAt < b.addedAt ? 1 : -1));
}

export async function getWallet(id: string): Promise<WalletRecord | null> {
  const out = await withStore("readonly", (store) =>
    txPromise<WalletRecord | undefined>(
      store.get(id) as IDBRequest<WalletRecord | undefined>,
      "get",
    ),
  );
  return out ?? null;
}

export async function findByFingerprintAndPath(
  fingerprint: string,
  path: string,
): Promise<WalletRecord | null> {
  const fp = fingerprint.toLowerCase();
  const matches = await withStore("readonly", (store) => {
    const idx = store.index("fingerprint");
    return txPromise<WalletRecord[]>(
      idx.getAll(fp) as IDBRequest<WalletRecord[]>,
      "fingerprint.getAll",
    );
  });
  return matches.find((w) => w.path === path) ?? null;
}

export async function removeWallet(id: string): Promise<void> {
  await withStore("readwrite", (store) =>
    txPromise(store.delete(id), "delete"),
  );
}

export async function updateLabel(id: string, label: string): Promise<void> {
  await withStore("readwrite", async (store) => {
    const cur = await txPromise<WalletRecord | undefined>(
      store.get(id) as IDBRequest<WalletRecord | undefined>,
      "get",
    );
    if (!cur) throw new WalletStoreError(`no wallet with id ${id}`);
    cur.label = label;
    await txPromise(store.put(cur), "put");
  });
}

export async function setLastScan(
  id: string,
  snapshot: WalletScanSnapshot,
): Promise<void> {
  await withStore("readwrite", async (store) => {
    const cur = await txPromise<WalletRecord | undefined>(
      store.get(id) as IDBRequest<WalletRecord | undefined>,
      "get",
    );
    if (!cur) throw new WalletStoreError(`no wallet with id ${id}`);
    cur.lastScan = snapshot;
    await txPromise(store.put(cur), "put");
  });
}

export async function clearLastScan(id: string): Promise<void> {
  await withStore("readwrite", async (store) => {
    const cur = await txPromise<WalletRecord | undefined>(
      store.get(id) as IDBRequest<WalletRecord | undefined>,
      "get",
    );
    if (!cur) throw new WalletStoreError(`no wallet with id ${id}`);
    delete cur.lastScan;
    await txPromise(store.put(cur), "put");
  });
}

export async function setNextReceiveIndex(
  id: string,
  index: number,
): Promise<void> {
  if (!Number.isInteger(index) || index < 0 || index >= 0x80000000) {
    throw new WalletStoreError(`nextReceiveIndex out of range: ${index}`);
  }
  await withStore("readwrite", async (store) => {
    const cur = await txPromise<WalletRecord | undefined>(
      store.get(id) as IDBRequest<WalletRecord | undefined>,
      "get",
    );
    if (!cur) throw new WalletStoreError(`no wallet with id ${id}`);
    cur.nextReceiveIndex = index;
    await txPromise(store.put(cur), "put");
  });
}

export async function setLastHistory(
  id: string,
  snapshot: HistorySnapshot,
): Promise<void> {
  await withStore("readwrite", async (store) => {
    const cur = await txPromise<WalletRecord | undefined>(
      store.get(id) as IDBRequest<WalletRecord | undefined>,
      "get",
    );
    if (!cur) throw new WalletStoreError(`no wallet with id ${id}`);
    cur.lastHistory = snapshot;
    await txPromise(store.put(cur), "put");
  });
}

export async function setDisplayUnit(
  id: string,
  unit: "sats" | "bsv" | "fiat",
): Promise<void> {
  await withStore("readwrite", async (store) => {
    const cur = await txPromise<WalletRecord | undefined>(
      store.get(id) as IDBRequest<WalletRecord | undefined>,
      "get",
    );
    if (!cur) throw new WalletStoreError(`no wallet with id ${id}`);
    cur.displayUnit = unit;
    await txPromise(store.put(cur), "put");
  });
}

/** Test-only helper. Wipes the entire object store. */
export async function _clearAllWallets(): Promise<void> {
  await withStore("readwrite", (store) => txPromise(store.clear(), "clear"));
}

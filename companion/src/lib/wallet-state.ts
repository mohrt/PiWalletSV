/**
 * Public mirror of the Pi's encrypted authoritative wallet state.
 *
 * Normal balance and spend paths read this mirror. Network discovery only
 * stages confirmed transaction packages; it cannot mutate spendable state
 * until the companion scans a Pi-authored revision/hash receipt.
 */
import {
  KIND_STATE_SYNC,
  bytesToHex,
  hexToBytes,
  splitAtomicBeef,
  type StateCoinT,
  type StateReceiptT,
  type StateSyncCoinT,
  type StateSyncT,
} from "./envelope.js";
import type { InputProof } from "./proof-fetcher.js";
import type { WalletUtxo } from "./utxo.js";
import { CHANGE_BRANCH, RECEIVE_BRANCH, deriveAddress } from "./derive.js";
import {
  setPendingStateSync,
  setWalletState,
  type WalletRecord,
} from "./wallets.js";
import type { HistorySnapshot, WalletTxEntry } from "./history.js";
import { Transaction } from "@bsv/sdk/transaction";
import { P2PKH } from "@bsv/sdk/script/templates";

export const WALLET_STATE_SCHEMA_VERSION = 1;
export const ZERO_STATE_HASH = new Uint8Array(32);

export interface StoredStateTransaction {
  txid: string;
  atomicBeef: Uint8Array;
}

export interface StoredHeaderAnchor {
  height: number;
  /** Raw byte order, matching envelope headerAnchors. */
  root: Uint8Array;
}

export interface WalletStateMirror {
  schemaVersion: number;
  revision: number;
  stateHash: Uint8Array;
  nextReceiveIndex: number;
  nextChangeIndex: number;
  coins: StateCoinT[];
  transactions: StoredStateTransaction[];
  headerAnchors: StoredHeaderAnchor[];
  updatedAt: string;
}

export interface PendingStateSync {
  requestId: string;
  coins: StateSyncCoinT[];
  headerAnchors: StoredHeaderAnchor[];
  createdAt: string;
}

export class WalletStateMirrorError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WalletStateMirrorError";
  }
}

function bytesFromBackup(value: unknown, field: string, length?: number): Uint8Array {
  if (!Array.isArray(value) || value.some((v) => !Number.isInteger(v) || v < 0 || v > 255)) {
    throw new WalletStateMirrorError(`${field} must be a byte array`);
  }
  const bytes = new Uint8Array(value as number[]);
  if (length !== undefined && bytes.length !== length) {
    throw new WalletStateMirrorError(`${field} must be ${length} bytes`);
  }
  return bytes;
}

function integerFromBackup(
  value: unknown,
  field: string,
  { min = 0, max = Number.MAX_SAFE_INTEGER }: { min?: number; max?: number } = {},
): number {
  if (!Number.isSafeInteger(value) || (value as number) < min || (value as number) > max) {
    throw new WalletStateMirrorError(`${field} must be an integer from ${min} to ${max}`);
  }
  return value as number;
}

function stateCoinFromBackup(raw: unknown, field: string): StateCoinT {
  if (typeof raw !== "object" || raw === null) {
    throw new WalletStateMirrorError(`${field} must be an object`);
  }
  const value = raw as Record<string, unknown>;
  const txid = String(value.txid);
  const transactionReference = String(value.transactionReference);
  const lockingScript = String(value.lockingScript);
  const derivation = value.derivation;
  const status = value.status;
  if (!/^[0-9a-fA-F]{64}$/.test(txid) ||
      !/^[0-9a-fA-F]{64}$/.test(transactionReference) ||
      !/^(?:[0-9a-fA-F]{2})+$/.test(lockingScript) ||
      !Array.isArray(derivation) || derivation.length !== 2 ||
      (derivation[0] !== 0 && derivation[0] !== 1)) {
    throw new WalletStateMirrorError(`${field} identity or derivation is invalid`);
  }
  const index = integerFromBackup(derivation[1], `${field}.derivation[1]`, {
    max: 0x7fffffff,
  });
  if (status !== "confirmed" && status !== "pending") {
    throw new WalletStateMirrorError(`${field}.status is invalid`);
  }
  const blockHeight = integerFromBackup(value.blockHeight, `${field}.blockHeight`);
  if ((status === "confirmed") !== (blockHeight > 0)) {
    throw new WalletStateMirrorError(`${field}.status does not match block height`);
  }
  return {
    txid,
    vout: integerFromBackup(value.vout, `${field}.vout`),
    sats: integerFromBackup(value.sats, `${field}.sats`, { min: 1 }),
    lockingScript,
    derivation: [derivation[0], index],
    status,
    transactionReference,
    blockHeight,
  };
}

/** JSON-safe encoding used by companion backup/migration. */
export function walletStateToBackup(value: WalletStateMirror | PendingStateSync): unknown {
  return JSON.parse(JSON.stringify(value, (_key, item: unknown) =>
    item instanceof Uint8Array ? Array.from(item) : item,
  ));
}

export function walletStateFromBackup(raw: unknown): WalletStateMirror {
  if (typeof raw !== "object" || raw === null) {
    throw new WalletStateMirrorError("walletState must be an object");
  }
  const value = raw as Record<string, unknown>;
  if (value.schemaVersion !== WALLET_STATE_SCHEMA_VERSION) {
    throw new WalletStateMirrorError("unsupported walletState schema");
  }
  if (!Array.isArray(value.coins) || !Array.isArray(value.transactions) ||
      !Array.isArray(value.headerAnchors)) {
    throw new WalletStateMirrorError("walletState arrays are invalid");
  }
  return {
    schemaVersion: WALLET_STATE_SCHEMA_VERSION,
    revision: integerFromBackup(value.revision, "walletState.revision"),
    stateHash: bytesFromBackup(value.stateHash, "walletState.stateHash", 32),
    nextReceiveIndex: integerFromBackup(
      value.nextReceiveIndex,
      "walletState.nextReceiveIndex",
      { max: 0x7fffffff },
    ),
    nextChangeIndex: integerFromBackup(
      value.nextChangeIndex,
      "walletState.nextChangeIndex",
      { max: 0x7fffffff },
    ),
    coins: value.coins.map((coin, index) =>
      stateCoinFromBackup(coin, `walletState.coins[${index}]`)),
    transactions: value.transactions.map((rawTx, index) => {
      const tx = rawTx as Record<string, unknown>;
      const txid = String(tx.txid);
      if (!/^[0-9a-fA-F]{64}$/.test(txid)) {
        throw new WalletStateMirrorError(`walletState.transactions[${index}].txid is invalid`);
      }
      return {
        txid,
        atomicBeef: bytesFromBackup(tx.atomicBeef, "walletState.atomicBeef"),
      };
    }),
    headerAnchors: value.headerAnchors.map((rawAnchor, index) => {
      const anchor = rawAnchor as Record<string, unknown>;
      return {
        height: integerFromBackup(
          anchor.height,
          `walletState.headerAnchors[${index}].height`,
          { min: 1 },
        ),
        root: bytesFromBackup(anchor.root, "walletState.headerRoot", 32),
      };
    }),
    updatedAt: String(value.updatedAt),
  };
}

export function pendingStateSyncFromBackup(raw: unknown): PendingStateSync {
  if (typeof raw !== "object" || raw === null) {
    throw new WalletStateMirrorError("pendingStateSync must be an object");
  }
  const value = raw as Record<string, unknown>;
  if (!Array.isArray(value.coins) || !Array.isArray(value.headerAnchors)) {
    throw new WalletStateMirrorError("pendingStateSync arrays are invalid");
  }
  const requestId = String(value.requestId).trim();
  if (!requestId || requestId.length > 128) {
    throw new WalletStateMirrorError("pendingStateSync.requestId is invalid");
  }
  return {
    requestId,
    createdAt: String(value.createdAt),
    coins: value.coins.map((rawCoin, index) => {
      const rawValue = rawCoin as Record<string, unknown>;
      const coin = stateCoinFromBackup(
        rawCoin,
        `pendingStateSync.coins[${index}]`,
      );
      if (coin.status !== "confirmed") {
        throw new WalletStateMirrorError("pendingStateSync coins must be confirmed");
      }
      return {
        ...coin,
        atomicBeef: bytesFromBackup(
          rawValue.atomicBeef,
          "pendingStateSync.atomicBeef",
        ),
      };
    }),
    headerAnchors: value.headerAnchors.map((rawAnchor, index) => {
      const anchor = rawAnchor as Record<string, unknown>;
      return {
        height: integerFromBackup(
          anchor.height,
          `pendingStateSync.headerAnchors[${index}].height`,
          { min: 1 },
        ),
        root: bytesFromBackup(anchor.root, "pendingStateSync.headerRoot", 32),
      };
    }),
  };
}

export function emptyWalletState(): WalletStateMirror {
  return {
    schemaVersion: WALLET_STATE_SCHEMA_VERSION,
    revision: 0,
    stateHash: ZERO_STATE_HASH.slice(),
    nextReceiveIndex: 0,
    nextChangeIndex: 0,
    coins: [],
    transactions: [],
    headerAnchors: [],
    updatedAt: new Date(0).toISOString(),
  };
}

function uuid(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return bytesToHex(bytes);
}

function sameBytes(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

function coinKey(coin: Pick<StateCoinT, "txid" | "vout">): string {
  return `${coin.txid}:${coin.vout}`;
}

export function stateBalanceSats(state: WalletStateMirror | undefined): number {
  return state?.coins.reduce((total, coin) => total + coin.sats, 0) ?? 0;
}

export function stateUtxos(state: WalletStateMirror | undefined): WalletUtxo[] {
  if (!state) return [];
  return state.coins.map((coin) => ({
    txid: coin.txid,
    vout: coin.vout,
    sats: coin.sats,
    height: coin.blockHeight,
    address: "",
    derivation: coin.derivation,
  }));
}

/** Rebuild display history from persisted Atomic BEEF without address APIs. */
export function historyFromState(wallet: WalletRecord): HistorySnapshot {
  const state = wallet.walletState;
  if (!state) {
    throw new WalletStateMirrorError("secured wallet state is required");
  }
  const ownedScripts = new Set<string>();
  const receiveEnd = Math.max(state.nextReceiveIndex, (wallet.nextReceiveIndex ?? 0) + 1);
  for (const [branch, end] of [[0, receiveEnd], [1, state.nextChangeIndex]] as const) {
    for (let index = 0; index < end; index++) {
      const address = deriveAddress(
        wallet.xpub,
        branch,
        index,
        wallet.network ?? "main",
      ).address;
      ownedScripts.add(new P2PKH().lock(address).toHex());
    }
  }

  const entries = new Map<string, WalletTxEntry>();
  for (const stored of state.transactions) {
    try {
      const tx = Transaction.fromAtomicBEEF(Array.from(stored.atomicBeef));
      const txid = tx.id("hex") as string;
      let received = 0;
      for (const output of tx.outputs) {
        if (ownedScripts.has(output.lockingScript.toHex())) {
          received += Number(output.satoshis);
        }
      }
      let spent = 0;
      for (const input of tx.inputs) {
        const source = input.sourceTransaction;
        const output = source?.outputs[input.sourceOutputIndex];
        if (output && ownedScripts.has(output.lockingScript.toHex())) {
          spent += Number(output.satoshis);
        }
      }
      entries.set(txid, {
        txid,
        timestamp: 0,
        blockHeight: tx.merklePath?.blockHeight ?? 0,
        deltaSats: received - spent,
      });
    } catch {
      // A corrupt mirror entry must not prevent rendering other committed txs.
    }
  }
  const sorted = [...entries.values()].sort((a, b) => {
    if (a.blockHeight === 0 && b.blockHeight !== 0) return -1;
    if (b.blockHeight === 0 && a.blockHeight !== 0) return 1;
    return b.blockHeight - a.blockHeight;
  });
  return {
    at: new Date().toISOString(),
    entries: sorted,
    addressesQueried: 0,
  };
}

export function proofFromState(
  state: WalletStateMirror,
  coin: StateCoinT,
): InputProof {
  const stored = state.transactions.find((tx) => tx.txid === coin.transactionReference);
  if (!stored) {
    throw new WalletStateMirrorError(
      `wallet state is missing transaction ${coin.transactionReference}`,
    );
  }
  const anchor = state.headerAnchors.find((a) => a.height === coin.blockHeight);
  if (!anchor || coin.blockHeight <= 0) {
    throw new WalletStateMirrorError(
      `wallet state is missing the confirmation anchor for ${coinKey(coin)}`,
    );
  }
  const { body } = splitAtomicBeef(stored.atomicBeef);
  return {
    beef: body,
    atomicBeef: stored.atomicBeef,
    merklePath: new Uint8Array(),
    height: coin.blockHeight,
    merkleRoot: bytesToHex(anchor.root.slice().reverse()),
  };
}

export function syncCoinFromProof(
  utxo: WalletUtxo,
  lockingScript: string,
  proof: InputProof,
): { coin: StateSyncCoinT; anchor: StoredHeaderAnchor } {
  if (!proof.atomicBeef) {
    throw new WalletStateMirrorError("proof did not include persistable Atomic BEEF");
  }
  const root = hexToBytes(proof.merkleRoot.replace(/^0x/, "")).reverse();
  return {
    coin: {
      txid: utxo.txid,
      vout: utxo.vout,
      sats: utxo.sats,
      lockingScript,
      derivation: utxo.derivation,
      status: "confirmed",
      transactionReference: utxo.txid,
      blockHeight: proof.height,
      atomicBeef: proof.atomicBeef,
    },
    anchor: { height: proof.height, root },
  };
}

export async function stageStateSyncCoins(
  wallet: WalletRecord,
  additions: Array<{ coin: StateSyncCoinT; anchor: StoredHeaderAnchor }>,
): Promise<PendingStateSync> {
  const current = wallet.pendingStateSync;
  const byOutpoint = new Map<string, StateSyncCoinT>();
  for (const coin of current?.coins ?? []) byOutpoint.set(coinKey(coin), coin);
  for (const { coin } of additions) byOutpoint.set(coinKey(coin), coin);
  const anchors = new Map<number, StoredHeaderAnchor>();
  for (const anchor of current?.headerAnchors ?? []) anchors.set(anchor.height, anchor);
  for (const { anchor } of additions) {
    const existing = anchors.get(anchor.height);
    if (existing && !sameBytes(existing.root, anchor.root)) {
      throw new WalletStateMirrorError(
        `conflicting Merkle roots for block ${anchor.height}`,
      );
    }
    anchors.set(anchor.height, anchor);
  }
  const pending: PendingStateSync = {
    requestId: current?.requestId ?? uuid(),
    coins: [...byOutpoint.values()],
    headerAnchors: [...anchors.values()].sort((a, b) => a.height - b.height),
    createdAt: current?.createdAt ?? new Date().toISOString(),
  };
  await setPendingStateSync(wallet.id, pending);
  wallet.pendingStateSync = pending;
  return pending;
}

/** Stage delivered Atomic BEEF without consulting an address indexer. */
export async function stageAtomicBeefPayment(
  wallet: WalletRecord,
  atomic: Uint8Array,
): Promise<PendingStateSync> {
  let tx: Transaction;
  try {
    tx = Transaction.fromAtomicBEEF(Array.from(atomic));
  } catch (e) {
    throw new WalletStateMirrorError(`Atomic BEEF parse failed: ${(e as Error).message}`);
  }
  if (!tx.merklePath) {
    throw new WalletStateMirrorError(
      "Atomic BEEF has no confirmation proof; wait for confirmation and import again",
    );
  }
  const txid = tx.id("hex") as string;
  const height = tx.merklePath.blockHeight;
  const root = hexToBytes(tx.merklePath.computeRoot(txid)).reverse();
  const scripts = new Map<string, { branch: number; index: number }>();
  const highestIssued = Math.max(
    wallet.nextReceiveIndex ?? 0,
    (wallet.walletState?.nextReceiveIndex ?? 0) - 1,
  );
  const nextChange = wallet.walletState?.nextChangeIndex ?? 0;
  for (const [branch, end] of [
    [RECEIVE_BRANCH, highestIssued + 1],
    [CHANGE_BRANCH, nextChange],
  ] as const) {
    for (let index = 0; index < end; index++) {
      const derived = deriveAddress(
        wallet.xpub,
        branch,
        index,
        wallet.network ?? "main",
      );
      scripts.set(new P2PKH().lock(derived.address).toHex(), { branch, index });
    }
  }
  const additions: Array<{ coin: StateSyncCoinT; anchor: StoredHeaderAnchor }> = [];
  tx.outputs.forEach((output, vout) => {
    const lockingScript = output.lockingScript.toHex();
    const match = scripts.get(lockingScript);
    if (!match) return;
    additions.push({
      coin: {
        txid,
        vout,
        sats: Number(output.satoshis),
        lockingScript,
        derivation: [match.branch, match.index],
        status: "confirmed",
        transactionReference: txid,
        blockHeight: height,
        atomicBeef: atomic,
      },
      anchor: { height, root },
    });
  });
  if (additions.length === 0) {
    throw new WalletStateMirrorError(
      "transaction has no output for an issued wallet address",
    );
  }
  return stageStateSyncCoins(wallet, additions);
}

export function buildStateSyncEnvelope(wallet: WalletRecord): StateSyncT {
  const pending = wallet.pendingStateSync;
  if (!pending || pending.coins.length === 0) {
    throw new WalletStateMirrorError("no confirmed payments are ready to secure");
  }
  const state = wallet.walletState ?? emptyWalletState();
  return {
    kind: KIND_STATE_SYNC,
    walletFp: hexToBytes(wallet.fingerprint),
    requestId: pending.requestId,
    expectedRevision: state.revision,
    expectedStateHash: state.stateHash,
    nextReceiveIndex: Math.max(
      state.nextReceiveIndex,
      (wallet.nextReceiveIndex ?? 0) + 1,
    ),
    nextChangeIndex: state.nextChangeIndex,
    coins: pending.coins,
    headerAnchors: new Map(
      pending.headerAnchors.map((anchor) => [anchor.height, anchor.root]),
    ),
  };
}

export async function applyStateReceipt(
  wallet: WalletRecord,
  receipt: StateReceiptT,
  signedAtomicBeef?: Uint8Array,
): Promise<WalletStateMirror> {
  if (bytesToHex(receipt.walletFp) !== wallet.fingerprint.toLowerCase()) {
    throw new WalletStateMirrorError("state receipt is for a different wallet");
  }
  const state = wallet.walletState ?? emptyWalletState();
  const initialReceipt = wallet.walletState === undefined && receipt.oldRevision === 0;
  if (
    receipt.oldRevision !== state.revision ||
    (!initialReceipt && !sameBytes(receipt.oldStateHash, state.stateHash))
  ) {
    throw new WalletStateMirrorError(
      "state receipt does not continue this companion's current revision",
    );
  }

  const coins = new Map(state.coins.map((coin) => [coinKey(coin), coin]));
  for (const key of receipt.removedOutpoints) coins.delete(key);
  for (const coin of receipt.addedCoins) coins.set(coinKey(coin), coin);

  const transactions = new Map(
    state.transactions.map((tx) => [tx.txid, tx] as const),
  );
  const anchors = new Map(
    state.headerAnchors.map((anchor) => [anchor.height, anchor] as const),
  );
  const pending = wallet.pendingStateSync;
  if (pending?.requestId === receipt.requestId) {
    for (const coin of pending.coins) {
      transactions.set(coin.transactionReference, {
        txid: coin.transactionReference,
        atomicBeef: coin.atomicBeef,
      });
    }
    for (const anchor of pending.headerAnchors) anchors.set(anchor.height, anchor);
  }
  if (signedAtomicBeef) {
    const { subjectTxidHex } = splitAtomicBeef(signedAtomicBeef);
    transactions.set(subjectTxidHex, {
      txid: subjectTxidHex,
      atomicBeef: signedAtomicBeef,
    });
  }

  const next: WalletStateMirror = {
    schemaVersion: WALLET_STATE_SCHEMA_VERSION,
    revision: receipt.newRevision,
    stateHash: receipt.newStateHash,
    nextReceiveIndex: Math.max(
      state.nextReceiveIndex,
      wallet.nextReceiveIndex ?? 0,
      ...receipt.addedCoins
        .filter((coin) => coin.derivation[0] === 0)
        .map((coin) => coin.derivation[1] + 1),
    ),
    nextChangeIndex: Math.max(
      state.nextChangeIndex,
      ...receipt.addedCoins
        .filter((coin) => coin.derivation[0] === 1)
        .map((coin) => coin.derivation[1] + 1),
    ),
    coins: [...coins.values()],
    transactions: [...transactions.values()],
    headerAnchors: [...anchors.values()].sort((a, b) => a.height - b.height),
    updatedAt: new Date().toISOString(),
  };
  await setWalletState(wallet.id, next);
  wallet.walletState = next;
  if (pending?.requestId === receipt.requestId) {
    await setPendingStateSync(wallet.id, undefined);
    delete wallet.pendingStateSync;
  }
  return next;
}

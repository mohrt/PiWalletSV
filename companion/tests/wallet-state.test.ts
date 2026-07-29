import "fake-indexeddb/auto";

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { beforeEach, describe, expect, it } from "vitest";
import { MerklePath, Transaction } from "@bsv/sdk/transaction";
import { P2PKH } from "@bsv/sdk/script/templates";

import {
  KIND_PROPOSAL,
  KIND_STATE_SYNC,
  decodeEnvelope,
  hexToBytes,
  type StateReceiptT,
  type UnsignedProposalT,
} from "../src/lib/envelope.js";
import {
  ZERO_STATE_HASH,
  WalletStateMirrorError,
  applyStateReceipt,
  buildStateSyncEnvelope,
  emptyWalletState,
  historyFromState,
  proofFromState,
  stageAtomicBeefPayment,
  stageStateSyncCoins,
  stateBalanceSats,
  stateUtxos,
  walletStateFromBackup,
  walletStateToBackup,
  type StoredHeaderAnchor,
  type WalletStateMirror,
} from "../src/lib/wallet-state.js";
import { CHANGE_BRANCH, deriveAddress } from "../src/lib/derive.js";
import {
  _clearAllWallets,
  addWallet,
  getWallet,
} from "../src/lib/wallets.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const FIXTURE_CBOR = join(__dirname, "../../tests/fixtures/proposal_01.cbor");
const DEMO = {
  label: "state test",
  xpub:
    "xpub6CdMDgU2hzWyeZ852LWqp5AfDz3ty2cRfi4jEw9BT8aNYugMQv" +
    "VykQsKLARZdbqKKp7yTviJdL1N9saYLmJNKD1rwVAwLTmU8r8qKeoyG4R",
  fingerprint: "cf987d8c",
  path: "m/44'/236'/0'",
  network: "main" as const,
};

function atomicBeef(txid: string, beef: Uint8Array): Uint8Array {
  const result = new Uint8Array(36 + beef.length);
  result.set([1, 1, 1, 1]);
  result.set(hexToBytes(txid).reverse(), 4);
  result.set(beef, 36);
  return result;
}

async function fixture(): Promise<UnsignedProposalT> {
  const decoded = await decodeEnvelope(new Uint8Array(readFileSync(FIXTURE_CBOR)));
  expect(decoded.kind).toBe(KIND_PROPOSAL);
  return decoded as UnsignedProposalT;
}

function mirrorWithFunding(
  proposal: UnsignedProposalT,
  transaction: Uint8Array,
): WalletStateMirror {
  const input = proposal.inputs[0]!;
  return {
    ...emptyWalletState(),
    revision: 1,
    stateHash: new Uint8Array(32).fill(7),
    nextReceiveIndex: 1,
    coins: [{
      txid: input.txid,
      vout: input.vout,
      sats: input.sats,
      lockingScript: "76a914751e76e8199196d454941c45d1b3a323f1433bd688ac",
      derivation: input.derivation,
      status: "confirmed",
      transactionReference: input.txid,
      blockHeight: [...proposal.headerAnchors.keys()][0]!,
    }],
    transactions: [{ txid: input.txid, atomicBeef: transaction }],
    headerAnchors: [...proposal.headerAnchors].map(([height, root]) => ({ height, root })),
    updatedAt: new Date().toISOString(),
  };
}

describe("Pi-authoritative wallet-state mirror", () => {
  beforeEach(async () => {
    await _clearAllWallets();
  });

  it("uses state coins for balance/UTXOs and persisted proofs", async () => {
    const proposal = await fixture();
    const transaction = atomicBeef(proposal.inputs[0]!.txid, proposal.inputs[0]!.beef);
    const state = mirrorWithFunding(proposal, transaction);

    expect(stateBalanceSats(state)).toBe(50_000);
    expect(stateUtxos(state)).toMatchObject([{ sats: 50_000, derivation: [0, 0] }]);
    const proof = proofFromState(state, state.coins[0]!);
    expect(proof.beef).toEqual(proposal.inputs[0]!.beef);
    expect(proof.atomicBeef).toEqual(transaction);
  });

  it("stages verified packages and builds a state-bound sync envelope", async () => {
    const proposal = await fixture();
    const wallet = await addWallet(DEMO);
    const input = proposal.inputs[0]!;
    const anchor: StoredHeaderAnchor = {
      height: [...proposal.headerAnchors.keys()][0]!,
      root: [...proposal.headerAnchors.values()][0]!,
    };
    await stageStateSyncCoins(wallet, [{
      coin: {
        txid: input.txid,
        vout: 0,
        sats: input.sats,
        lockingScript: "76a914751e76e8199196d454941c45d1b3a323f1433bd688ac",
        derivation: [0, 0],
        status: "confirmed",
        transactionReference: input.txid,
        blockHeight: anchor.height,
        atomicBeef: atomicBeef(input.txid, input.beef),
      },
      anchor,
    }]);

    const sync = buildStateSyncEnvelope(wallet);
    expect(sync.kind).toBe(KIND_STATE_SYNC);
    expect(sync.expectedRevision).toBe(0);
    expect(sync.expectedStateHash).toEqual(ZERO_STATE_HASH);
    expect(sync.coins).toHaveLength(1);
  });

  it("recognizes confirmed state-issued change without address discovery", async () => {
    const wallet = await addWallet(DEMO);
    wallet.walletState = {
      ...emptyWalletState(),
      revision: 1,
      stateHash: new Uint8Array(32).fill(3),
      nextChangeIndex: 1,
    };
    const change = deriveAddress(wallet.xpub, CHANGE_BRANCH, 0, wallet.network);
    const tx = new Transaction();
    tx.addOutput({
      lockingScript: new P2PKH().lock(change.address),
      satoshis: 19_500,
    });
    const txid = tx.id("hex") as string;
    tx.merklePath = MerklePath.fromCoinbaseTxidAndHeight(txid, 900_000);

    const pending = await stageAtomicBeefPayment(
      wallet,
      new Uint8Array(tx.toAtomicBEEF()),
    );
    expect(pending.coins).toMatchObject([{
      txid,
      sats: 19_500,
      derivation: [CHANGE_BRANCH, 0],
      status: "confirmed",
      blockHeight: 900_000,
    }]);
  });

  it("accepts only a continuing Pi receipt and persists its mirror", async () => {
    const wallet = await addWallet(DEMO);
    const proposal = await fixture();
    const input = proposal.inputs[0]!;
    const transaction = atomicBeef(input.txid, input.beef);
    const anchor = {
      height: [...proposal.headerAnchors.keys()][0]!,
      root: [...proposal.headerAnchors.values()][0]!,
    };
    const pending = await stageStateSyncCoins(wallet, [{
      coin: {
        txid: input.txid,
        vout: 0,
        sats: input.sats,
        lockingScript: "76a914751e76e8199196d454941c45d1b3a323f1433bd688ac",
        derivation: [0, 0],
        status: "confirmed",
        transactionReference: input.txid,
        blockHeight: anchor.height,
        atomicBeef: transaction,
      },
      anchor,
    }]);
    const receipt: StateReceiptT = {
      kind: "stateReceipt",
      walletFp: hexToBytes(wallet.fingerprint),
      requestId: pending.requestId,
      oldRevision: 0,
      newRevision: 1,
      oldStateHash: ZERO_STATE_HASH,
      newStateHash: new Uint8Array(32).fill(9),
      addedCoins: pending.coins,
      removedOutpoints: [],
    };

    const state = await applyStateReceipt(wallet, receipt);
    expect(state.revision).toBe(1);
    expect(state.transactions).toEqual([{ txid: input.txid, atomicBeef: transaction }]);
    expect((await getWallet(wallet.id))?.pendingStateSync).toBeUndefined();

    await expect(applyStateReceipt(wallet, receipt)).rejects.toBeInstanceOf(
      WalletStateMirrorError,
    );
  });

  it("rebuilds incoming history from local Atomic BEEF with no address lookup", async () => {
    const proposal = await fixture();
    const wallet = await addWallet(DEMO);
    const transaction = atomicBeef(proposal.inputs[0]!.txid, proposal.inputs[0]!.beef);
    wallet.walletState = mirrorWithFunding(proposal, transaction);

    const history = historyFromState(wallet);
    expect(history.addressesQueried).toBe(0);
    expect(history.entries).toMatchObject([{
      txid: proposal.inputs[0]!.txid,
      deltaSats: 50_000,
      blockHeight: [...proposal.headerAnchors.keys()][0],
    }]);
  });

  it("round-trips byte fields through JSON-safe backup encoding", async () => {
    const proposal = await fixture();
    const transaction = atomicBeef(proposal.inputs[0]!.txid, proposal.inputs[0]!.beef);
    const state = mirrorWithFunding(proposal, transaction);
    const restored = walletStateFromBackup(walletStateToBackup(state));

    expect(restored).toEqual(state);
    expect(restored.stateHash).toBeInstanceOf(Uint8Array);
    expect(restored.transactions[0]!.atomicBeef).toBeInstanceOf(Uint8Array);
  });

  it("rejects malformed counters and coin status in migration backups", async () => {
    const proposal = await fixture();
    const transaction = atomicBeef(proposal.inputs[0]!.txid, proposal.inputs[0]!.beef);
    const state = mirrorWithFunding(proposal, transaction);
    const badCounter = walletStateToBackup(state) as Record<string, unknown>;
    badCounter.nextReceiveIndex = 0x80000000;
    expect(() => walletStateFromBackup(badCounter)).toThrow(WalletStateMirrorError);

    const badCoin = walletStateToBackup(state) as Record<string, unknown>;
    const coins = badCoin.coins as Array<Record<string, unknown>>;
    coins[0]!.status = "pending";
    expect(() => walletStateFromBackup(badCoin)).toThrow(/block height/);
  });
});

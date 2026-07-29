# Persistent wallet state

PiWalletSV keeps keys in `vault.bin` and transaction facts in a separate,
encrypted `state.bin`. This makes normal balance, history, receive, and spend
operations proportional to the transactions being processed instead of the
number of addresses ever issued.

The design follows the same broad separation used by
[Vault Manager](https://github.com/bsv-blockchain/vault-manager): coins refer
to transactions in a deduplicated BEEF store, proofs and anchors are retained,
and changes are journaled. PiWalletSV keeps its existing air-gapped QR UX and
does not adopt Vault Manager's application surface or key model.

## Why keys are not enough

A BIP39 seed deterministically recovers keys, but it does not encode:

- which outputs currently exist or have been spent;
- the BRC-62/BRC-95 transaction data and BRC-74 Merkle paths already verified;
- the receive and change counters already issued;
- an in-flight signed transaction that was committed before a power loss; or
- a transaction journal for local history.

Reconstructing those facts by walking `m/0/*` and `m/1/*` until a gap is both
indexer-dependent and unbounded as a wallet ages. A fully-spent address also
cannot be treated as unused without querying address history, which makes the
usual shortcut incorrect.

## Authority boundary

The Pi is authoritative. The companion holds a public mirror in IndexedDB.

| Owner | Persistent data | Authority |
| --- | --- | --- |
| Pi `vault.bin` | encrypted account xprv, PIN policy, wallet metadata | signing keys |
| Pi `state.bin` | coins, Atomic BEEF, anchors, counters, pending spends, journal | spendable state |
| Companion IndexedDB | xpub plus Pi-authored state revision/hash and public transaction mirror | UI/cache only |

The companion may stage a transaction package, but it cannot make it
spendable by updating IndexedDB. The Pi first verifies the package, commits a
new state revision, and returns a receipt. The companion applies only a receipt
that continues its current revision and hash.

## Encrypted file and recovery key

Each wallet entry in `state.bin` is encrypted independently with AES-256-GCM.
The key is derived from a reserved hardened child of the account xprv, followed
by HKDF-SHA256 with the domain `PiWalletSV/state.bin/AES-256-GCM/v1` and the
wallet fingerprint as salt.

Consequences:

- the paired xpub cannot derive the state key;
- changing the PIN does not change the state key;
- recreating the wallet from the same mnemonic/path derives the same key; and
- a new vault UUID does not prevent a backed-up state file from being opened.

The outer CBOR file exposes only routing metadata: fingerprint, account path,
network, schema version, and ciphertext. Those identity fields are also bound
as AES-GCM associated data. Plain transaction IDs, amounts, BEEF, counters, and
journal entries remain inside the authenticated ciphertext.

## State record

The current schema stores:

- monotonic `stateRevision` and `previousStateHash`;
- `nextReceiveIndex` and `nextChangeIndex`;
- coins keyed by `txid:vout`, including amount, locking script, derivation,
  confirmation state, transaction reference, and block height;
- a deduplicated `transactionReference -> Atomic BEEF` store;
- retained `height -> Merkle root` anchors;
- pending signed responses for safe re-export after restart; and
- an append-only transition journal.

The state hash is SHA-256 over canonical CBOR. Self-referential result-hash
fields are excluded from the digest, while the rest of the journal and pending
record remains hash-protected. Every decrypt validates the genesis link,
monotonic revisions, inter-event hash links, final state hash, pending-spend
journal references, and Atomic BEEF transaction references before returning
state to a caller.

## Receive transition

1. A sender or service supplies BRC-95 Atomic BEEF for a confirmed payment.
   The companion can also obtain the same package during explicit migration.
2. The companion identifies outputs for receive addresses it has already
   issued and stages the coin, Atomic BEEF, derivation, and header anchor.
3. The user chooses **Secure payments** on the Pi and scans `stateSync`.
4. The Pi checks the wallet fingerprint, expected revision/hash, Atomic BEEF
   subject transaction, output amount/script, declared derivation, BRC-74
   Merkle path, block height, and supplied anchor.
5. The Pi atomically writes the new encrypted state and displays a
   `stateReceipt` QR.
6. The companion applies the coin/transaction delta only after scanning that
   receipt.

Unconfirmed incoming payments remain outside secured state until a confirmation
proof exists. Change created by a signed spend is retained as pending state so
the same transaction can be re-exported safely after a restart.

When that change confirms, delivered Atomic BEEF for the transaction stages a
normal `stateSync` update from pending to confirmed. The companion recognizes
both issued receive scripts and state-issued change scripts locally; it does not
need to enumerate either branch through an address service.

## Spend transition

1. Coin selection reads the companion's Pi-authored mirror. It never performs
   an address scan and it reuses the persisted BEEF/anchor for each input.
2. The proposal includes `stateRevision`, `stateHash`, and a unique
   `proposalId` in addition to the existing v2 fields.
3. Before verification or signing, the Pi rejects an incomplete, unbound, or
   stale proposal when state is active.
4. After the existing SPV/change/amount/fee checks and user confirmation, the
   Pi signs the transaction.
5. Before displaying the signed QR, the Pi atomically removes spent coins,
   inserts pending change, stores the signed Atomic BEEF, advances counters,
   journals the transition, and persists a replayable signed response.
6. The signed envelope contains the Pi-authored state receipt. The companion
   applies it before broadcasting.

If power is lost after step 5, **Re-export signed tx** returns the exact
persisted response. The proposal is never signed a second time.

## Compatibility and migration

Envelope version remains `2`; every state field and the two state message
kinds are additive. Existing v2 xpub, proposal, and signed envelopes still
decode.

An empty-state Pi accepts exactly one legacy unbound proposal. It verifies the
proposal's existing BEEF and anchors, adopts those input facts, consumes them,
and commits the change output in one transition. After that transition all
proposals must carry a current state binding.

Existing companion `lastScan` data remains readable for display and backup,
but it is not spendable authority. The user runs **Advanced → Disaster
recovery discovery** once to stage the recovered coins and then secures them
on the Pi. That recovery walker queries address history as well as UTXOs, so a
fully-spent address cannot terminate the BIP44 gap walk early.

Normal **Balance**, **History**, **Receive**, and **Send** paths do not enumerate
addresses. Balance reads coins, History parses retained Atomic BEEF locally,
Receive advances persisted counters, and Send reuses retained proofs. Address
gap discovery exists only behind the explicit, confirmation-gated Advanced
recovery action.

## Backup and failure behavior

USB bundle version 2 contains:

```text
manifest.json
vault.bin
state.bin
settings.json  # optional
```

The manifest is written last and contains a SHA-256 checksum for every included
file. Restore validates all checksums before replacing device files. AES-GCM
provides authentication for the state contents; manifest hashes primarily
detect incomplete copies and accidental corruption.

`piwallet backup import` restores keys and state together. After recreating a
wallet from its mnemonic, `piwallet backup import-state` restores only the
encrypted state snapshot. A mnemonic without `state.bin` still controls the
funds, but recovering the current UTXO set then requires the explicit disaster
walker or another wallet's recovery scan.

File replacement uses write, flush, `fsync`, and atomic rename. A state
transition is committed before any signed response is shown, so a QR that can
escape the Pi always has a corresponding durable journal entry.

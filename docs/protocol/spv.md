# SPV verification — v2

A PiWalletSV signer has **no network access** by design. Everything
it "knows" about the chain has to be supplied by the companion in
the `unsigned_proposal` envelope and cross-checked locally before
any signature is produced. This document specifies the verification
machinery for envelope schema v2.

The cryptographic primitives align with:

- [BRC-62](https://bsv.brc.dev/transactions/0062) — BEEF, the bundle
  that carries each input's prior funding tx + Merkle path.
- [BRC-67](https://bsv.brc.dev/transactions/0067) — SPV, the rules
  for accepting a chain state without a full node.
- [BRC-74](https://bsv.brc.dev/transactions/0074) — BUMP, the
  Merkle-path encoding that lives inside BEEF.
- [BRC-95](https://bsv.brc.dev/transactions/0095) — Atomic BEEF, the
  single-transaction wrapping used for the `signed_tx` payload.

PiWalletSV is **not** BRC-100 (the high-level wallet RPC surface);
see [`../brc-alignment.md`](../brc-alignment.md) for the rationale.

## 1. Trust model

PiWalletSV v2 occupies a deliberate middle ground between "no SPV"
and full BRC-67 strong SPV. The Pi:

- **Does** verify, byte for byte, that every input's BUMP path
  computes to the merkle root the proposal claims for its block.
- **Does** re-derive every signing key, every input's locking
  script, and the change output's locking script from the wallet's
  account xpub. A lying companion can never trick the Pi into
  signing for a different key, paying to a different change
  address, or inflating an input's satoshi value.
- **Does not** independently validate that the claimed
  `(height, merkle_root)` correspondence is on the canonical longest
  chain. Instead, the proposal carries a small `header_anchors` map
  (one entry per unique block referenced by the inputs); the Pi
  takes those entries on faith.

The companion sources each entry by fetching the block's header
from a trusted block-explorer source (WhatsOnChain by default). A
malicious companion or a compromised explorer can therefore at most
cause the Pi to sign a transaction whose inputs do not exist on
chain. The broadcast then fails: there is nothing to spend. The
user's keys, funds, and change re-derivation are unaffected. There
is no path by which an anchor lie translates into stolen funds.

This is a hobbyist-Pi-wallet tradeoff: it eliminates the cold-sync
cost of downloading and PoW-validating thousands of headers in
exchange for a slightly larger trusted base. A future PiWalletSV
revision may add an opt-in "strong SPV" mode that re-introduces a
header chain in the proposal; if so, it will be a documented schema
bump, not a silent change.

## 2. The "verify, then sign" rule

A v2 signer MUST run **all** of the following checks before
producing any signature for a proposal. If any check fails, the
signer MUST abort signing and surface a user-visible reason. It
MUST NOT emit a partial signature, MUST NOT store any signing
state, and MUST NOT leak any private material through error
messages.

1. **Envelope shape.** Every `unsigned_proposal` field listed in
   [`envelopes.md`](envelopes.md) §4 is present and well-typed.
   Envelopes with `v != 2` MUST be rejected; v1 producers must be
   upgraded.
2. **Wallet match.** `walletFp` resolves to a known wallet whose
   account xpub the signer can derive at `m/44'/236'/0'`.
3. **Header anchors.** `header_anchors` is non-empty and every
   value is exactly 32 bytes (a raw merkle root). The map covers
   every height referenced by an input's BUMP path; missing or
   extra entries are a hard reject.
4. **Fee rate cap.** `feeRate` does not exceed the signer's
   user-configurable maximum (the reference implementation
   defaults to `5000 sats/kB` and refuses anything higher unless
   the operator explicitly raises the cap on-device).
5. **Per-input check.** For each input `i`:
   - `i.beef` parses as a valid BEEF (BRC-62; see §3 below).
   - The prior funding transaction is recoverable from the BEEF
     and its txid matches `i.txid`.
   - The funding tx has a Merkle path attached (BRC-74 BUMP), and
     `merklePath.computeRoot(i.txid)` equals
     `header_anchors[merklePath.blockHeight]` rendered as
     displayed-hex.
   - The funding tx's output at index `i.vout` exists and its
     locking script is P2PKH.
   - The locking script equals
     `P2PKH(derive_address(xpub, i.derivation))`.
   - `i.sats` equals the funding tx output's actual satoshi
     value.
6. **Change re-derivation.** The output at `changeIndex` MUST
   satisfy
   `outputs[changeIndex].script == P2PKH(derive_address(xpub, changeDerivation))`.
   v2 (like v1) requires every proposal to carry an explicit
   change output; signers MUST reject proposals where the check
   fails or where `changeIndex` is out of range.
7. **Conservation of value.**
   `sum(input.prevout_sats) >= sum(output.sats)`. The implicit
   miner fee is the difference and MUST be non-negative.
8. **Locktime sanity.** `locktime` is a uint within
   `[0, 0xFFFFFFFF]`. The signer MAY refuse non-zero locktimes if
   the operator has not opted in.

After all checks succeed, the signer MAY proceed to derive the
per-input private keys from the account xprv, sign each input,
and emit a `signed_tx` envelope (see §5). The signer MUST NOT
consult any of the companion's claimed satoshi values, claimed
P2PKH addresses, or claimed merkle roots once verification has
passed — every value used in signing MUST come from the parsed
prior transactions and the verified anchors.

## 3. BEEF (BRC-62)

BEEF (Background Evaluation Extended Format) is the canonical BSV
SPV bundle. The PiWalletSV signer uses BEEF as the source of the
prior transactions referenced by each input.

For the purposes of PiWalletSV v2 interop, a companion building
`ProposalInput.beef` MUST produce bytes that satisfy:

1. `Transaction.fromBeef(bytes)` in `@bsv/sdk` (TypeScript) and
   `Transaction.from_beef(bytes)` in `bsv-sdk` (Python) both parse
   successfully.
2. The resulting top-level `Transaction` either **is** the prior
   funding tx itself, or contains an input whose
   `source_transaction` is the prior funding tx. The reference Pi
   verifier accepts both layouts.
3. The prior funding tx's attached `merkle_path` (BRC-74 BUMP) is
   present and resolves to the matching root in `header_anchors`.

A companion building a proposal does **not** need to include the
spending transaction inside the BEEF — only the prior funding tx
and its proof. This keeps payloads small.

## 4. Merkle path (BRC-74 BUMP, embedded in BEEF)

The Merkle path is carried *inside* the BEEF; v2 dropped the
redundant per-input standalone `merklePath` field that v1 also
carried. A v2 signer obtains the path via `tx.merkle_path` after
parsing the BEEF.

The path's `computeRoot(txid)` MUST equal the merkle root the
proposal supplies via `header_anchors[blockHeight]`. A mismatch is
a hard reject.

When constructing a Merkle path from an external block-explorer
proof (such as the TSC / BRC-10 form), a companion MUST handle
**duplicate-sibling** entries correctly. In BSV's right-leaning
tree layout, when a level has an odd number of nodes the last
node is hashed against itself; a TSC proof represents this with a
`"*"` marker at that level. The reference companion translates a
TSC proof into BUMP form by walking levels from the leaf up and
producing one entry per level, marking the duplicate position with
`{ duplicate: true }`.

The exact algorithm the reference companion uses is in
`companion/src/lib/proof-fetcher.ts`'s `tscProofToMerklePath`
function. Third-party companions may take a different route as
long as `MerklePath.computeRoot(txid)` produces the same root the
chain records for that block.

## 5. `signed_tx` envelope (BRC-95 Atomic BEEF)

After a successful sign, the signer emits a `signed_tx` envelope
whose payload is **Atomic BEEF (BRC-95)**: a 4-byte magic prefix,
the 32-byte subject TXID (raw byte order), then the BRC-62 BEEF
body for the signed transaction. The companion:

1. Parses the Atomic BEEF wrapper to recover the subject TXID
   without needing to re-hash the inner tx.
2. Decodes the inner BEEF to extract the raw signed transaction
   bytes for broadcast.
3. Verifies, before calling its broadcast endpoint, that the
   broadcaster echoes back the same TXID the Atomic BEEF
   declared. A mismatch is surfaced to the user as a malleability
   warning.

See [`envelopes.md`](envelopes.md) §5 for the full envelope shape.

## 6. Expectations for a third-party companion

If you are building a third-party companion, the minimum you must
produce for a PiWalletSV signer to accept your proposal is:

1. A correctly-shaped v2 `unsigned_proposal` envelope per
   [`envelopes.md`](envelopes.md).
2. A `header_anchors` map covering every block referenced by an
   input's BUMP path. Each value is the block's merkle root in
   raw byte order (32 bytes), sourced from a block-explorer
   request you trust.
3. For each input:
   - A BRC-62 BEEF blob containing the prior funding tx with its
     BRC-74 BUMP attached.
   - An accurate `sats` value (the signer re-checks; mis-claiming
     just aborts the sign).
   - A correct `derivation` `[branch, index]` pair for the
     input's locking script.
4. An explicit change output whose `script` equals
   `P2PKH(derive_address(xpub, changeDerivation))`. v2 (like v1)
   always requires change.
5. A `walletFp` that matches the signer's stored fingerprint for
   the target wallet.

You are free to use any UTXO discovery strategy, any coin
selection algorithm, any block-explorer backend, and any fee
rate (subject to the signer's local cap). The signer doesn't know
or care about those decisions.

A companion that is unable to obtain a BEEF for an input, or
cannot resolve the input's confirming block to a merkle root,
cannot produce a v2 proposal — the signer will not sign
unanchored inputs.

## 7. Expectations for a third-party signer

If you are building a third-party signer (a Pi alternative, an
HSM adapter, an air-gapped phone app), the PiWalletSV companion
will:

1. Send you v2 `unsigned_proposal` envelopes whose `walletFp`
   matches an `xpub_export` envelope you previously emitted to the
   companion.
2. Expect you to return a `signed_tx` envelope (BRC-95 Atomic
   BEEF) with the same `walletFp`.
3. Verify, before broadcasting, that the TXID embedded in the
   Atomic BEEF matches the inner BEEF body, and that the
   broadcaster echoes back the same value.

The companion does **not** require your signer to implement every
check listed in §2, but it strongly RECOMMENDS them — they are the
guarantees the signer provides to the *user*, not to the companion.
A signer that skips them silently is dangerous to its operator.

## 8. Threat model summary

The verification rules above are designed to defeat the following
attacks by a malicious or compromised companion (or its network
infrastructure):

| Attack                                                       | Defeated by                                                            |
| ------------------------------------------------------------ | ---------------------------------------------------------------------- |
| Tell the signer it has a UTXO it doesn't.                    | BRC-62 BEEF + BRC-74 BUMP + anchored merkle root match (§2.5).         |
| Forge a BEEF whose path doesn't match the anchored root.     | BUMP `computeRoot(txid)` ↔ `header_anchors[height]` byte equality.    |
| Inflate the input's claimed satoshi value.                   | `i.sats == prior.outputs[i.vout].satoshis` check (§2.5).               |
| Lie about which derivation index funds an input.             | `derive_address` ↔ prevout-script match (§2.5).                        |
| Lie about which output is "change".                          | Change re-derivation check (§2.6).                                     |
| Submit a different tx than the user reviewed.                | All output scripts and amounts are user-visible on bonnet.             |

The signer **cannot** defeat:

- A companion (or compromised block-explorer) that supplies a
  fabricated `(height, merkle_root)` anchor for a block that
  doesn't exist on the canonical chain. This produces a
  signed-but-unbroadcastable transaction; funds and keys remain
  safe.
- A user who confirms a transaction without reading the bonnet
  screen.
- A user who entered a recipient address that was already wrong
  (e.g., the companion got phished into showing the wrong
  address during a copy-paste).
- A multi-week chain reorg that retroactively invalidates the
  block the input was confirmed in. Anchors are point-in-time
  snapshots from the explorer; subsequent reorgs are out of scope.

The bonnet UX is therefore the security perimeter the user must
inspect; the cryptographic checks make sure that whatever the user
*sees* is what gets signed, with the explicit caveat that "this
input exists on chain" is a property the user delegates to the
companion's block-explorer source.

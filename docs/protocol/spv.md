# SPV verification — v2

A PiWalletSV signer has **no network access** by design. Everything
it "knows" about the chain has to be supplied by the companion in
the `unsigned_proposal` envelope and cross-checked locally before
any signature is produced. This document specifies the verification
machinery for envelope schema v2; for the v1 `headerAnchors` model
this replaces, see the [git history](../../) of this file.

The rules in this document are mandatory for v2. A signer that
skips any of them is not conformant and SHOULD NOT be advertised as
PiWalletSV-compatible. The cryptographic primitives align with:

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

## 1. The "verify, then sign" rule

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
3. **Header chain validation.** `verify_chain(headers, checkpoint)`
   succeeds — see [`headers.md`](headers.md) for the full rules.
   This produces a `height → merkle_root` map the signer derives
   locally, replacing the trusted-`headerAnchors` model from v1.
4. **Confirmation depth.** Every input's funding tx is at least
   `MIN_CONFIRMATION_DEPTH` (=6) blocks deep in the validated
   chain.
5. **Fee rate cap.** `feeRate` does not exceed the signer's
   user-configurable maximum (the reference implementation
   defaults to `5000 sats/kB` and refuses anything higher unless
   the operator explicitly raises the cap on-device).
6. **Per-input SPV check.** For each input `i`:
   - `i.beef` parses as a valid BEEF (BRC-62; see §2 below).
   - The prior funding transaction is recoverable from the BEEF
     and its txid matches `i.txid`.
   - The funding tx has a Merkle path attached (BRC-74 BUMP), and
     `merklePath.computeRoot(i.txid)` equals the merkle root the
     validated chain has at `merklePath.blockHeight`.
   - The funding tx's output at index `i.vout` exists and its
     locking script is P2PKH.
   - The locking script equals
     `P2PKH(derive_address(xpub, i.derivation))`.
   - `i.sats` equals the funding tx output's actual satoshi
     value.
7. **Change re-derivation.** The output at `changeIndex` MUST
   satisfy
   `outputs[changeIndex].script == P2PKH(derive_address(xpub, changeDerivation))`.
   v2 (like v1) requires every proposal to carry an explicit
   change output; signers MUST reject proposals where the check
   fails or where `changeIndex` is out of range.
8. **Conservation of value.**
   `sum(input.prevout_sats) >= sum(output.sats)`. The implicit
   miner fee is the difference and MUST be non-negative.
9. **Locktime sanity.** `locktime` is a uint within
   `[0, 0xFFFFFFFF]`. The signer MAY refuse non-zero locktimes if
   the operator has not opted in.

After all checks succeed, the signer MAY proceed to derive the
per-input private keys from the account xprv, sign each input,
and emit a `signed_tx` envelope (see §6). The signer MUST NOT
consult any of the companion's claimed satoshi values, claimed
P2PKH addresses, or claimed merkle roots once verification has
passed — every value used in signing MUST come from the parsed
prior transactions and the validated chain.

## 2. BEEF (BRC-62)

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
   present and resolves to the matching root in the validated
   header chain.

A companion building a proposal does **not** need to include the
spending transaction inside the BEEF — only the prior funding tx
and its proof. This keeps payloads small.

## 3. Merkle path (BRC-74 BUMP, embedded in BEEF)

The Merkle path is carried *inside* the BEEF; v2 dropped the
redundant per-input standalone `merklePath` field that v1 also
carried. A v2 signer obtains the path via `tx.merkle_path` after
parsing the BEEF.

The path's `computeRoot(txid)` MUST equal the merkle root the
signer pulled from the validated header chain at the path's
`blockHeight`. A mismatch is a hard reject.

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

## 4. Header chain (BRC-67, with checkpoint anchor)

The validated header chain is the trust spine of v2 SPV. See
[`headers.md`](headers.md) for the complete specification:

- 80-byte header layout (§2.1)
- Per-header validation: structure, linkage, self-consistent PoW
  (§3)
- Confirmation-depth requirement (§4)
- Firmware checkpoints and their rotation procedure (§5)
- Threat model (§6)

This document references the chain at the level of "for each
input's `merklePath.blockHeight`, look up the merkle root in the
validated map and compare". The mechanics of producing that map
are entirely in `headers.md`.

A signer MUST display, before signing:

- The chain's tip height (the highest height in the validated
  range).
- The firmware checkpoint's height (the trust anchor used).
- For each input, the height + Merkle root the path resolved
  against, plus a "✓ SPV-verified" marker if so.

The reference bonnet UI paints these as short prefixes; full
hashes are available on a long-press for users who want to
cross-check against a public block explorer.

## 5. Expectations for a third-party companion

If you are building a third-party companion, the minimum you must
produce for a PiWalletSV signer to accept your proposal is:

1. A correctly-shaped v2 `unsigned_proposal` envelope per
   [`envelopes.md`](envelopes.md).
2. A `headers` chain that:
   - Starts at `checkpointHeight + 1`,
   - Links unbroken back to one of the firmware-baked checkpoint
     hashes for the wallet's network,
   - Extends at least `MIN_CONFIRMATION_DEPTH = 6` blocks past
     the deepest input's confirmation height,
   - Has every header self-consistently clear its declared `bits`
     target.
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

A companion that is unable to obtain a BEEF for an input, or a
header chain that meets the depth requirement, cannot produce a v2
proposal — the signer will not sign unanchored or shallowly-buried
inputs.

## 6. `signed_tx` envelope (BRC-95 Atomic BEEF)

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
check listed in §1, but it strongly RECOMMENDS them — they are the
guarantees the signer provides to the *user*, not to the companion.
A signer that skips them silently is dangerous to its operator.

## 8. Threat model summary

The verification rules above are designed to defeat the following
attacks by a malicious or compromised companion (or its network
infrastructure):

| Attack                                                       | Defeated by                                                    |
| ------------------------------------------------------------ | -------------------------------------------------------------- |
| Tell the signer it has a UTXO it doesn't.                    | BRC-62 BEEF + BRC-74 BUMP + chain-derived merkle root (§1.6).   |
| Forge an `(height, root)` anchor for a non-existent block.   | Header chain PoW + linkage check from checkpoint (`headers.md`). |
| Replay an old, unfunded prior tx with a stale Merkle path.   | Confirmation-depth rule + chain-derived root (§1.4 + §1.6).     |
| Inflate the input's claimed satoshi value.                   | `i.sats == prior.outputs[i.vout].satoshis` check (§1.6).        |
| Lie about which derivation index funds an input.             | `derive_address` ↔ prevout-script match (§1.6).                 |
| Lie about which output is "change".                          | Change re-derivation check (§1.7).                              |
| Submit a different tx than the user reviewed.                | All output scripts and amounts are user-visible on bonnet.     |
| Ship a testnet chain to a mainnet wallet (or vice versa).    | Network-pinned checkpoint anchors (`headers.md` §5).            |

The signer cannot defeat:

- A user who confirms a transaction without reading the bonnet
  screen.
- A user who entered a recipient address that was already wrong
  (e.g., the companion got phished into showing the wrong
  address during a copy-paste).
- A multi-week chain reorg deeper than `MIN_CONFIRMATION_DEPTH`.

The bonnet UX is therefore the security perimeter the user must
inspect; the cryptographic checks make sure that whatever the user
*sees* is what gets signed.

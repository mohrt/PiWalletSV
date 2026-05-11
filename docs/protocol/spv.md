# SPV verification — v1

A PiWalletSV signer has **no network access** by design. Everything it
"knows" about the chain has to be supplied by the companion in the
`unsigned_proposal` envelope and cross-checked locally before any
signature is produced. This document specifies what that material
looks like, what the signer is required to verify, and what a
companion has to supply to satisfy a conformant signer.

The rules in this document are mandatory for v1. A signer that
skips any of them is not conformant and SHOULD NOT be advertised as
PiWalletSV-compatible.

## 1. The "verify, then sign" rule

A v1 signer MUST run **all** of the following checks before
producing any signature for a proposal. If any check fails, the
signer MUST abort signing and surface a user-visible reason. It MUST
NOT emit a partial signature, MUST NOT store any signing state, and
MUST NOT leak any private material through error messages.

1. **Envelope shape.** Every `unsigned_proposal` field listed in
   [`envelopes.md`](envelopes.md) §4 is present and well-typed.
2. **Wallet match.** `walletFp` resolves to a known wallet whose
   account xpub the signer can derive at `m/44'/236'/0'`.
3. **At least one input** and **at least one header anchor.**
4. **Fee rate cap.** `feeRate` does not exceed the signer's
   user-configurable maximum (the reference implementation defaults
   to `5000 sats/kB` and refuses anything higher unless the operator
   explicitly raises the cap on-device).
5. **Per-input SPV check.** For each input `i`:
   - `i.beef` parses as a valid BEEF (see §2 below).
   - The prior funding transaction is recoverable from the BEEF and
     its txid matches `i.txid`.
   - The funding tx has a Merkle path attached, and
     `merklePath.computeRoot(i.txid)` equals
     `headerAnchors[merklePath.blockHeight]`.
   - The funding tx's output at index `i.vout` exists and its
     locking script is P2PKH.
   - The locking script equals `P2PKH(derive_address(xpub, i.derivation))`.
   - `i.sats` equals the funding tx output's actual satoshi value.
6. **Change re-derivation.** The output at `changeIndex` MUST
   satisfy
   `outputs[changeIndex].script ==`
   `P2PKH(derive_address(xpub, changeDerivation))`. v1 requires
   every proposal to carry an explicit change output; signers MUST
   reject proposals where the check fails or where `changeIndex` is
   out of range. (Companions that exhaust the input value through
   the recipient + fee should fold the residue into the fee rather
   than omitting change — see [`envelopes.md`](envelopes.md) §4.3.)
7. **Conservation of value.** `sum(input.prevout_sats) >=
   sum(output.sats)`. The implicit miner fee is the difference and
   MUST be non-negative.
8. **Locktime sanity.** `locktime` is a uint within
   `[0, 0xFFFFFFFF]`. The signer MAY refuse non-zero locktimes if
   the operator has not opted in.

After all checks succeed, the signer MAY proceed to derive the
per-input private keys from the account xprv, sign each input, and
emit a `signed_tx` envelope. The signer MUST NOT consult any of the
companion's claimed satoshi values, claimed P2PKH addresses, or
claimed BEEF roots once verification has passed — every value used
in signing MUST come from the parsed prior transactions.

## 2. BEEF

BEEF (Background Evaluation Extended Format) is the canonical BSV
SPV bundle. Its full specification is BRC-62 in the BSV BRC list
(`bsv-blockchain/BRCs/transactions/0062.md`). The PiWalletSV signer
uses BEEF as the source of the prior transactions referenced by
each input.

For the purposes of PiWalletSV v1 interop, a companion building
`ProposalInput.beef` MUST produce bytes that satisfy:

1. `Transaction.fromBeef(bytes)` in `@bsv/sdk` (TypeScript) and
   `Transaction.from_beef(bytes)` in `bsv-sdk` (Python) both parse
   successfully.
2. The resulting top-level `Transaction` either **is** the prior
   funding tx itself, or contains an input whose
   `source_transaction` is the prior funding tx. (The reference Pi
   verifier accepts both layouts.)
3. The prior funding tx's attached `merkle_path` is present and
   resolves to the matching header anchor.

A companion building a proposal does **not** need to include the
spending transaction inside the BEEF — only the prior funding tx
and its proof. This keeps payloads small.

If you cannot use a BEEF library, you can construct a minimal BEEF
manually: it is just the prior transaction bytes plus its Merkle
path, framed per BRC-62. The reference companion uses
`@bsv/sdk`'s `Beef.fromTx(...)` helper to assemble it.

## 3. Merkle path

The per-input `merklePath` field is the same Merkle path in
standalone binary form (BRC-58). It MUST decode via
`@bsv/sdk`'s `MerklePath.fromBinary(...)` or `bsv-sdk`'s
`MerklePath.from_binary(...)`.

When constructing a Merkle path from an external block-explorer
proof (such as the TSC / BRC-10 form), a companion MUST handle
**duplicate-sibling** entries correctly. In BSV's right-leaning tree
layout, when a level has an odd number of nodes the last node is
hashed against itself; a TSC proof represents this with a `"*"`
marker at that level. The reference companion translates a TSC
proof into `MerklePath` form by walking levels from the leaf up and
producing one entry per level, marking the duplicate position with
`{ duplicate: true }`.

The exact algorithm the reference companion uses is in
`companion/src/lib/proof-fetcher.ts`'s `tscProofToMerklePath`
function. Third-party companions may take a different route as long
as `MerklePath.computeRoot(txid)` produces the same root the chain
records for that block.

The signer cross-checks the path's root against `headerAnchors`,
which carries the user-displayed root from a header the user has
accepted on the bonnet screen.

## 4. Header anchors

`headerAnchors` maps **block height** to **block Merkle root**:

- Block height is a CBOR uint, the same height number block
  explorers display.
- Block Merkle root is exactly 32 bytes, in **big-endian display
  form** — the byte order that block explorers print. (BSV stores
  it little-endian on the wire; the anchor is the display form so
  the user can read it off the bonnet and compare to a block
  explorer if they want to.)

A companion MUST emit one anchor for every distinct
`merklePath.blockHeight` referenced by any input's BEEF. It MAY emit
more (no harm), but it MUST NOT omit any.

A signer MUST:

- Refuse to verify any input whose `merklePath.blockHeight` is not a
  key in `headerAnchors`.
- Display each `(height, root)` pair to the user during the "review
  & sign" step. The reference bonnet UI paints them as 8-char
  height + 8-char short root prefix; this is the user's last
  defense against a colluding online infrastructure that lies about
  the chain.

The signer MUST NOT trust any external source for the anchors — it
treats them as user-asserted facts. A companion can (and the
reference one does) fetch headers from a block-explorer endpoint
and forward them, but ultimately the user is the source of trust.

## 5. Expectations for a third-party companion

If you are building a third-party companion, the minimum you must
produce for a PiWalletSV signer to accept your proposal is:

1. A correctly-shaped `unsigned_proposal` envelope per
   [`envelopes.md`](envelopes.md).
2. For each input:
   - A BEEF blob containing the prior funding tx with its
     Merkle path attached.
   - A standalone `MerklePath` binary equivalent to the one inside
     the BEEF.
   - An accurate `sats` value (the signer re-checks; mis-claiming
     just aborts the sign).
   - A correct `derivation` `[branch, index]` pair for the input's
     locking script.
3. An explicit change output whose `script` equals
   `P2PKH(derive_address(xpub, changeDerivation))`. v1 always requires
   change; if your selected UTXO set can't leave above-dust change,
   either pick a different set or surface the limitation to the user.
4. A `headerAnchors` map covering every block height referenced.
5. A `walletFp` that matches the signer's stored fingerprint for
   the target wallet.

You are free to use any UTXO discovery strategy, any coin selection
algorithm, any block-explorer backend, and any fee rate (subject to
the signer's local cap). The signer doesn't know or care about
those decisions.

A companion that is unable to obtain a BEEF or Merkle path from its
chosen backend cannot produce a v1 proposal — the signer will not
sign unanchored inputs.

## 6. Expectations for a third-party signer

If you are building a third-party signer (a Pi alternative, a HSM
adapter, an air-gapped phone app), the PiWalletSV companion will:

1. Send you `unsigned_proposal` envelopes whose `walletFp` matches
   an `xpub_export` envelope you previously emitted to the
   companion.
2. Expect you to return a `signed_tx` envelope with the same
   `walletFp` and a valid signed BSV transaction in `rawHex`.
3. Verify, before broadcasting, that the returned `txid` matches
   the `rawHex` and that the txid the broadcaster echoes is the
   same one you signed (a difference is surfaced to the user as a
   malleability warning).

The companion does **not** require your signer to implement every
check listed in §1, but it strongly RECOMMENDS them — they are the
guarantees the signer provides to the *user*, not to the companion.
A signer that skips them silently is dangerous to its operator.

## 7. Threat model summary

The verification rules above are designed to defeat the following
attacks by a malicious or compromised companion (or its network
infrastructure):

| Attack                                          | Defeated by                                                |
| ----------------------------------------------- | ---------------------------------------------------------- |
| Tell the signer it has a UTXO it doesn't.       | BEEF + Merkle path + header anchor check (§1.5).            |
| Inflate the input's claimed satoshi value.      | `i.sats == prior.outputs[i.vout].satoshis` check (§1.5).    |
| Lie about which derivation index funds an input. | `derive_address` ↔ prevout-script match (§1.5).             |
| Lie about which output is "change".             | Change re-derivation check (§1.6).                          |
| Steal funds via a clever signed tx (e.g., RBF). | Conservation of value + non-P2PKH-script rejection.         |
| Submit a different tx than the user reviewed.   | All output scripts and amounts are user-visible on bonnet. |

The signer cannot defeat:

- A user who confirms a transaction without reading the bonnet
  screen.
- A user who entered a recipient address that was already wrong
  (e.g., the companion got phished into showing the wrong address
  during a copy-paste).

The bonnet UX is therefore the security perimeter the user must
inspect; the cryptographic checks make sure that whatever the user
*sees* is what gets signed.

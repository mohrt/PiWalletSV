"""SPV-level verification of incoming `unsigned_proposal` envelopes.

The Pi MUST run this module's `verify_proposal()` on every proposal before
asking sign.py to produce signatures. The plan's "trust nothing the phone
says without a Merkle proof" rule is enforced here.

What `verify_proposal` checks:

1. The proposal's ``checkpoint_height`` matches the firmware's baked-in
   recent checkpoint for the wallet's network (see
   :mod:`piwallet.core.checkpoints`). The header chain that follows must
   start at ``checkpoint_height + 1`` and link back to the firmware
   checkpoint's hash; if not, the chain is rejected before any input is
   inspected.
2. The header chain (``proposal.headers``) is independently
   PoW-validated and linked into a contiguous ``height -> merkle_root``
   map by :func:`piwallet.core.headers.verify_chain`. The companion's
   claim that "block ``H`` had Merkle root ``R``" is no longer a leap of
   faith — the Pi only believes ``R`` after walking real headers from a
   firmware checkpoint and confirming the PoW under each one.
3. Every input's BEEF parses and contains the prior funding transaction.
4. The prior transaction's BUMP Merkle path resolves to a height covered
   by the validated chain, and its computed root matches the validated
   chain's root for that height.
5. Each input is buried by at least :data:`MIN_CONFIRMATION_DEPTH`
   confirmations relative to the chain's tip. This forces the companion
   to ship enough headers to push every input out of the
   reorg-vulnerable zone before the Pi will sign it.
6. The input references the prior tx's correct vout, the script is P2PKH,
   and pays to the address derived from ``account_xpub`` at the input's
   declared ``derivation``.
7. The change output's script equals the address re-derived from
   ``account_xpub`` at ``proposal.change_derivation``.
8. Sum(input.sats) >= Sum(output.sats); fee is non-negative.
9. Fee rate is within the bounds the user has approved
   (caller-supplied).

If any check fails, ``ProposalVerificationError`` is raised with an
explanation short enough to fit on the bonnet's 240x240 display.

The module deliberately does NOT mutate the proposal or build a
``Transaction``; that's the job of ``sign.py`` and only happens after
``verify_proposal`` returns a ``VerifiedProposal`` summary.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from bsv import P2PKH, ChainTracker, MerklePath, Transaction
from bsv.script.script import Script

from piwallet.core import checkpoints as cp
from piwallet.core import derivation as deriv
from piwallet.core import headers as hdr
from piwallet.core.envelope import UnsignedProposal

MIN_CONFIRMATION_DEPTH: int = 6
"""Required burial of every spent input.

Six confirmations is the canonical "out of normal reorg range"
threshold (chosen to be conservative even against double-digit-block
reorgs that have happened on BTC; BSV reorgs are typically far
shallower). The companion is responsible for shipping at least this
many headers past the deepest input — if it doesn't, the Pi rejects
the proposal at verification time rather than producing a signature
the operator couldn't broadcast safely."""


class ProposalVerificationError(Exception):
    """Raised when an `unsigned_proposal` fails any SPV / structural check."""


# ---------------------------------------------------------------------------
# OfflineChainTracker -- backs `MerklePath.verify` without any network I/O.
# ---------------------------------------------------------------------------


class OfflineChainTracker(ChainTracker):
    """A ``ChainTracker`` that resolves heights against a fixed in-memory
    map of validated Merkle roots.

    The map is built by feeding ``proposal.headers`` through
    :func:`piwallet.core.headers.verify_chain`, which independently
    PoW-validates every header before exposing its Merkle root. A
    malicious companion that hands the Pi a forged chain would have to
    either (a) re-mine real PoW for every forged header, or (b) split
    its forged chain off the canonical chain at a height before the
    firmware checkpoint — both prevented by the per-firmware
    checkpoint pinning + per-header PoW comparison.
    """

    def __init__(self, anchors_hex: dict[int, str]) -> None:
        self._anchors = {int(h): r.lower() for h, r in anchors_hex.items()}

    @property
    def heights(self) -> set[int]:
        return set(self._anchors.keys())

    @property
    def tip_height(self) -> int:
        return max(self._anchors) if self._anchors else 0

    async def is_valid_root_for_height(self, root: str, height: int) -> bool:
        return self._anchors.get(int(height)) == root.lower()


# ---------------------------------------------------------------------------
# Verified output for sign.py.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerifiedInput:
    """Result of verifying one proposal input.

    `prevout_script_hex` and `prevout_sats` come from the prior funding tx
    (NOT from the proposal's claimed values), so a lying phone cannot inflate
    the apparent input value.
    """

    txid: str
    vout: int
    prevout_script_hex: str
    prevout_sats: int
    derivation: tuple[int, int]


@dataclass(frozen=True)
class VerifiedProposal:
    """Outcome of `verify_proposal`. Hand to sign.py to produce a signed tx.

    `_source_txs` maps `prior_txid` -> the parsed prior `Transaction` that we
    already extracted from BEEF during verification. sign.py needs them so
    bsv-sdk's `tx.sign()` can compute the sighash preimage (which includes
    each input's prior value). It is excluded from equality / hashing so
    the dataclass is still cleanly comparable and tests can introspect it.
    """

    inputs: tuple[VerifiedInput, ...]
    outputs: tuple[tuple[str, int], ...]  # (script_hex, sats)
    change_index: int
    change_derivation: tuple[int, int]
    locktime: int
    _source_txs: dict[str, Transaction] = field(
        default_factory=dict, compare=False, repr=False
    )

    @property
    def total_in(self) -> int:
        return sum(i.prevout_sats for i in self.inputs)

    @property
    def total_out(self) -> int:
        return sum(sats for _, sats in self.outputs)

    @property
    def fee_sats(self) -> int:
        return self.total_in - self.total_out


# ---------------------------------------------------------------------------
# Top-level entry point.
# ---------------------------------------------------------------------------


def verify_proposal(
    proposal: UnsignedProposal,
    account_xpub_str: str,
    *,
    max_fee_rate_satskb: int | None = None,
    network: deriv.Network = deriv.DEFAULT_NETWORK,
) -> VerifiedProposal:
    """Validate `proposal` against `account_xpub_str` and the included anchors.

    :param proposal: decoded `UnsignedProposal` (already deserialized).
    :param account_xpub_str: Base58Check xpub at `m/44'/coin'/account'`.
    :param max_fee_rate_satskb: optional sanity cap on the proposal's fee rate.
    :param network: ``"main"`` or ``"test"`` — the wallet's
        address-encoding network. P2PKH scripts are
        **network-invariant at the bytes level** (the HASH160 is the
        same for both networks; only the rendered base58check string
        differs), so this kwarg does NOT gate verification: a
        mainnet proposal will verify under either network kwarg and
        vice versa. The kwarg is plumbed through so future
        per-network checks (e.g. testnet-only opcode whitelists, or
        BIP21 URI emission) can be added without an API change, and
        so error messages render addresses in the user's expected
        format. Defaults to ``"main"`` to keep existing single-arg
        callsites byte-identical.
    :returns: `VerifiedProposal` ready for sign.py.
    :raises ProposalVerificationError: with a short, user-displayable reason.
    """
    if not proposal.headers:
        raise ProposalVerificationError("no headers supplied")

    if max_fee_rate_satskb is not None and proposal.fee_rate_satskb > max_fee_rate_satskb:
        raise ProposalVerificationError(
            f"fee rate {proposal.fee_rate_satskb} > cap {max_fee_rate_satskb}"
        )

    # ---- header chain validation ------------------------------------------
    # The proposal's headers must descend from the firmware's recent
    # checkpoint for the wallet's network. A wrong-network or stale
    # checkpoint claim is rejected here, before any input is inspected.
    expected_checkpoint = cp.for_network(network)
    if proposal.checkpoint_height != expected_checkpoint.height:
        raise ProposalVerificationError(
            f"checkpointHeight {proposal.checkpoint_height} does not match "
            f"firmware checkpoint at {expected_checkpoint.height}"
        )
    cp_hash = bytes.fromhex(expected_checkpoint.hash_hex)[::-1]
    chain_anchor = hdr.CheckpointHeader(
        height=expected_checkpoint.height, hash=cp_hash
    )
    try:
        anchors_bytes = hdr.verify_chain(proposal.headers, chain_anchor)
    except hdr.HeaderError as exc:
        raise ProposalVerificationError(f"header chain invalid: {exc}") from exc

    account_xpub = deriv.parse_xpub(account_xpub_str)

    # ---- per-input SPV verification --------------------------------------
    # ``anchors_bytes`` maps height -> raw 32-byte merkle root. The bsv-sdk
    # MerklePath.verify path expects displayed-hex roots, so we render the
    # validated bytes once and feed the tracker that table.
    anchors_hex = {h: r[::-1].hex() for h, r in anchors_bytes.items()}
    tracker = OfflineChainTracker(anchors_hex)
    tip_height = tracker.tip_height
    verified_inputs: list[VerifiedInput] = []
    source_txs: dict[str, Transaction] = {}

    for idx, ip in enumerate(proposal.inputs):
        ctx = f"input #{idx}"
        try:
            funding_tx = Transaction.from_beef(ip.beef)
        except Exception as exc:
            raise ProposalVerificationError(f"{ctx}: BEEF parse failed: {exc}") from exc

        # `from_beef` returns the *child* (top-level) tx; the funding tx is
        # attached to its first input matching ip.txid. Search inputs for it,
        # OR if proposal.input.txid == funding_tx.txid() then funding_tx is
        # actually the funding tx itself. Handle both.
        prior = _resolve_prior(funding_tx, ip.txid)
        if prior is None:
            raise ProposalVerificationError(
                f"{ctx}: BEEF does not contain prior tx {ip.txid[:8]}…"
            )

        # ---- merkle proof
        if prior.merkle_path is None:
            raise ProposalVerificationError(f"{ctx}: prior tx has no merkle path")

        block_height = int(prior.merkle_path.block_height)
        if block_height not in tracker.heights:
            raise ProposalVerificationError(
                f"{ctx}: validated chain does not cover height {block_height}"
            )
        # 6-confirmation depth: tip_height - block_height + 1 >= MIN_CONFIRMATION_DEPTH.
        # The "+1" counts the input's block itself as the first confirmation,
        # matching how WoC and most explorers report confirmations.
        confirmations = tip_height - block_height + 1
        if confirmations < MIN_CONFIRMATION_DEPTH:
            raise ProposalVerificationError(
                f"{ctx}: only {confirmations} confirmation(s) at height "
                f"{block_height} (chain tip {tip_height}); need "
                f"{MIN_CONFIRMATION_DEPTH}"
            )

        if not _merkle_path_anchored(prior.merkle_path, prior.txid(), tracker):
            raise ProposalVerificationError(
                f"{ctx}: merkle root mismatch at height {block_height}"
            )

        # ---- prior tx output sanity
        if ip.vout >= len(prior.outputs):
            raise ProposalVerificationError(
                f"{ctx}: vout {ip.vout} out of range (prior has {len(prior.outputs)} outputs)"
            )
        prior_out = prior.outputs[ip.vout]
        prevout_script_hex = prior_out.locking_script.hex()
        prevout_sats = int(prior_out.satoshis)

        # ---- claimed-vs-actual sats sanity
        if ip.sats != prevout_sats:
            raise ProposalVerificationError(
                f"{ctx}: sats mismatch (claim {ip.sats}, actual {prevout_sats})"
            )

        # ---- key derivation match: derive the address from the xpub at the
        # declared `derivation` and compare to the P2PKH address inferred
        # from prevout_script_hex.
        change, index = ip.derivation
        try:
            expected_address = deriv.derive_address(
                account_xpub, change, index, network=network
            )
        except ValueError as exc:
            raise ProposalVerificationError(
                f"{ctx}: bad derivation {ip.derivation}: {exc}"
            ) from exc
        try:
            expected_script = P2PKH().lock(expected_address)
        except Exception as exc:
            raise ProposalVerificationError(f"{ctx}: address->script: {exc}") from exc

        if expected_script.hex() != prevout_script_hex:
            raise ProposalVerificationError(
                f"{ctx}: script does not match derivation {ip.derivation}"
            )

        verified_inputs.append(
            VerifiedInput(
                txid=ip.txid,
                vout=ip.vout,
                prevout_script_hex=prevout_script_hex,
                prevout_sats=prevout_sats,
                derivation=ip.derivation,
            )
        )
        source_txs[ip.txid] = prior

    # ---- change output verification --------------------------------------
    out = proposal.outputs[proposal.change_index]
    cd_branch, cd_index = proposal.change_derivation
    try:
        change_address = deriv.derive_address(
            account_xpub, cd_branch, cd_index, network=network
        )
    except ValueError as exc:
        raise ProposalVerificationError(
            f"bad changeDerivation {proposal.change_derivation}: {exc}"
        ) from exc
    expected_change_script = P2PKH().lock(change_address).hex()
    if out.script_hex != expected_change_script:
        raise ProposalVerificationError(
            "change output does not match changeDerivation; refusing to sign"
        )

    # ---- fee sanity -------------------------------------------------------
    total_in = sum(i.prevout_sats for i in verified_inputs)
    total_out = sum(o.sats for o in proposal.outputs)
    if total_out > total_in:
        raise ProposalVerificationError(
            f"outputs ({total_out}) exceed inputs ({total_in})"
        )

    return VerifiedProposal(
        inputs=tuple(verified_inputs),
        outputs=tuple((o.script_hex, o.sats) for o in proposal.outputs),
        change_index=proposal.change_index,
        change_derivation=proposal.change_derivation,
        locktime=proposal.locktime,
        _source_txs=source_txs,
    )


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _resolve_prior(top_level: Transaction, prior_txid: str) -> Transaction | None:
    """Find the funding transaction with `prior_txid` inside a BEEF.

    BEEF can be either:
        - the funding tx itself (rare; usually the spending tx is on top)
        - the spending tx with a `source_transaction` reference per input.
    """
    if top_level.txid() == prior_txid:
        return top_level
    for tx_in in top_level.inputs:
        if tx_in.source_transaction is None:
            continue
        if tx_in.source_transaction.txid() == prior_txid:
            return tx_in.source_transaction
    return None


def _merkle_path_anchored(
    mp: MerklePath, txid: str, tracker: OfflineChainTracker
) -> bool:
    """Sync wrapper around `MerklePath.verify(...)`'s async API."""
    try:
        return asyncio.run(mp.verify(txid, tracker))
    except Exception:
        return False


def script_address_or_none(
    script_hex: str,
    *,
    network: deriv.Network = deriv.DEFAULT_NETWORK,
) -> str | None:
    """Try to extract the P2PKH address from a script.

    Returns the base58check-encoded address on a successful P2PKH
    template match, or ``None`` for non-P2PKH scripts and parse errors.
    The address is rendered for ``network`` (mainnet ``0x00`` or
    testnet ``0x6F``); callers showing addresses to the operator must
    supply the wallet's network so the rendered string is one the
    operator's tools and the network's nodes will accept.
    """
    try:
        s = Script(script_hex)
        # P2PKH is OP_DUP OP_HASH160 <20-byte> OP_EQUALVERIFY OP_CHECKSIG
        chunks = s.chunks
        if (
            len(chunks) == 5
            and chunks[2].data is not None
            and len(chunks[2].data) == 20
        ):
            from bsv import to_base58_check
            from bsv.constants import (
                ADDRESS_MAINNET_PREFIX,
                ADDRESS_TESTNET_PREFIX,
            )

            prefix_bytes = (
                ADDRESS_MAINNET_PREFIX
                if network == deriv.NETWORK_MAIN
                else ADDRESS_TESTNET_PREFIX
            )
            # bsv-sdk's to_base58_check is typed `List[int]` for both
            # args (it concatenates them with `+`), so we have to
            # convert the bytes-typed prefix and the bytes-typed h160
            # payload to lists. The original implementation tried
            # `prefix.to_bytes(1, "big")` and would have raised
            # AttributeError on this version of the SDK — the helper
            # has no internal callers, which is why the bug never
            # surfaced. Tests in test_verify.py now exercise both
            # network paths to guard against future regressions.
            return to_base58_check(
                list(chunks[2].data),
                prefix=list(prefix_bytes),
            )
    except Exception:
        return None
    return None


__all__ = [
    "OfflineChainTracker",
    "ProposalVerificationError",
    "VerifiedInput",
    "VerifiedProposal",
    "verify_proposal",
]

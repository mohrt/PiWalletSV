"""Build and sign a previously-verified transaction proposal.

`verify_then_sign` is the only public entry point an interactive caller
needs: it accepts a raw `UnsignedProposal`, runs `verify.verify_proposal`,
then derives signing keys and produces the signed `Transaction`.

The plan's iron-clad rule lives here: we never sign anything that
`verify_proposal` did not return as a `VerifiedProposal`. The two-step API
also exists (`build_signed_tx`) for callers that want to verify and sign
in separate phases (e.g. show "verified — review on screen — confirm" UX).

Memory hygiene:

- Signing keys are dropped as soon as the transaction is signed.
- The xprv passed in is consumed via a single closure call; we don't keep
  it on any module-level state.
- On a Pi, the caller (CLI/UI) should re-encrypt or zero its xprv buffer
  immediately after this returns.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from bsv import P2PKH, PrivateKey, Transaction
from bsv.script.script import Script
from bsv.transaction_input import TransactionInput
from bsv.transaction_output import TransactionOutput

from piwallet.core.envelope import SignedTx, UnsignedProposal
from piwallet.core.verify import (
    VerifiedInput,
    VerifiedProposal,
    verify_proposal,
)


class SigningError(Exception):
    """Raised on any failure during signing (post-verify)."""


# Signature for a callback that, given (change, index), returns the leaf
# PrivateKey. The vault's `derive_signing_key` matches this shape (after
# binding pin/wallet_id).
KeyDeriver = Callable[[int, int], PrivateKey]


@dataclass(frozen=True)
class SignedResult:
    """Output of `build_signed_tx` / `verify_then_sign`."""

    raw_hex: str
    txid: str
    size: int
    fee_sats: int
    verified: VerifiedProposal


def build_signed_tx(
    verified: VerifiedProposal,
    derive_key: KeyDeriver,
) -> SignedResult:
    """Construct, sign, and serialize the transaction implied by `verified`.

    :param verified: result of `verify.verify_proposal` (carries the prior
        `source_transaction` for each input).
    :param derive_key: callback `(change, index) -> PrivateKey`. Typical use:
        `partial(vault.derive_signing_key, pin, wallet_id)`.
    :returns: SignedResult.
    :raises SigningError: on any signing failure.
    """
    tx_inputs: list[TransactionInput] = []
    keys_used: list[PrivateKey] = []

    try:
        for vin in verified.inputs:
            sk = derive_key(*vin.derivation)
            keys_used.append(sk)

            source_tx = verified._source_txs.get(vin.txid)
            if source_tx is None:
                raise SigningError(
                    f"missing source_transaction for input {vin.txid[:8]}…; "
                    "VerifiedProposal must come from verify_proposal()"
                )

            tx_inputs.append(
                TransactionInput(
                    source_transaction=source_tx,
                    source_txid=vin.txid,
                    source_output_index=vin.vout,
                    unlocking_script_template=P2PKH().unlock(sk),
                )
            )

        tx_outputs: list[TransactionOutput] = [
            TransactionOutput(Script(script_hex), sats)
            for script_hex, sats in verified.outputs
        ]

        tx = Transaction(
            tx_inputs=tx_inputs,
            tx_outputs=tx_outputs,
            version=1,
            locktime=verified.locktime,
        )
        try:
            tx.sign()
        except Exception as exc:
            raise SigningError(f"sign() failed: {exc}") from exc

        # Sanity check: every input now has a non-empty unlocking script.
        for i, txi in enumerate(tx.inputs):
            if txi.unlocking_script is None or len(txi.unlocking_script.serialize()) == 0:
                raise SigningError(f"input {i} unsigned after sign() call")

        return SignedResult(
            raw_hex=tx.hex(),
            txid=tx.txid(),
            size=tx.size(),
            fee_sats=verified.fee_sats,
            verified=verified,
        )
    finally:
        # Best-effort: drop our references to the leaf keys ASAP.
        keys_used.clear()


def verify_then_sign(
    proposal: UnsignedProposal,
    account_xpub_str: str,
    derive_key: KeyDeriver,
    *,
    max_fee_rate_satskb: int | None = None,
    network: str = "main",
) -> SignedResult:
    """Single call that runs `verify_proposal` then `build_signed_tx`.

    ``network`` is forwarded to :func:`verify.verify_proposal` so the
    change re-derivation address is rendered with the wallet's
    network prefix; mismatches between proposal-side and wallet-side
    networks fail at the change-script equality check.

    The caller still benefits from getting back the `verified` field so it
    can render the verified totals to the user before relaying the QR back.
    """
    verified = verify_proposal(
        proposal,
        account_xpub_str,
        max_fee_rate_satskb=max_fee_rate_satskb,
        network=network,  # type: ignore[arg-type]
    )
    return build_signed_tx(verified, derive_key)


def to_signed_envelope(result: SignedResult, wallet_fp: bytes) -> SignedTx:
    """Wrap a `SignedResult` into a `SignedTx` envelope ready to encode."""
    return SignedTx(
        wallet_fp=wallet_fp,
        raw_hex=result.raw_hex,
        txid=result.txid,
    )


def _verified_inputs_summary(inputs: tuple[VerifiedInput, ...]) -> str:
    """Short string for display/log purposes."""
    return ", ".join(f"{i.txid[:8]}:{i.vout} {i.prevout_sats}sat" for i in inputs)


__all__ = [
    "KeyDeriver",
    "SignedResult",
    "SigningError",
    "build_signed_tx",
    "to_signed_envelope",
    "verify_then_sign",
]

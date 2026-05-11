"""PiWallet CLI: dev-time interface to the offline core.

This is NOT the bonnet UI; that lives in `piwallet/ui/` and arrives in
Phase 2. The CLI is for:

- Generating and validating mnemonics during bring-up.
- Loading a vault from disk and printing wallet metadata.
- End-to-end signing of an `unsigned_proposal` blob (the signature path).
- Decoding any envelope blob into a human-readable summary.

It is intentionally minimal -- one command per top-level workflow. PIN
prompts use `click.prompt(hide_input=True)` so they don't echo to a
terminal.
"""

from __future__ import annotations

import sys
from functools import partial
from pathlib import Path

import click

from piwallet import __version__
from piwallet.core import derivation as deriv
from piwallet.core import envelope as env
from piwallet.core import mnemonic as mnem
from piwallet.core import sign as sgn
from piwallet.core import verify as vfy
from piwallet.core.vault import (
    Vault,
    VaultError,
    VaultWipedError,
    WrongPinError,
)


@click.group(help="PiWallet offline signing CLI.")
@click.version_option(__version__, prog_name="piwallet")
def main() -> None:
    pass


# ---- mnemonic commands -------------------------------------------------


@main.group(help="BIP39 mnemonic utilities.")
def mnemonic() -> None:
    pass


@mnemonic.command("new", help="Generate a fresh BIP39 mnemonic.")
@click.option("--words", type=click.Choice(["12", "24"]), default="12", show_default=True)
def mnemonic_new(words: str) -> None:
    phrase = mnem.generate(int(words))
    click.echo(phrase)


@mnemonic.command("validate", help="Validate a mnemonic from stdin.")
def mnemonic_validate() -> None:
    phrase = click.get_text_stream("stdin").read().strip()
    try:
        mnem.validate(phrase)
    except mnem.MnemonicError as exc:
        click.echo(f"INVALID: {exc}", err=True)
        sys.exit(1)
    click.echo("OK")


# ---- vault commands ----------------------------------------------------


@main.group(help="Encrypted vault operations.")
@click.option(
    "--vault-path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path.home() / ".piwallet-dev" / "vault.bin",
    show_default=True,
    help="Path to the encrypted vault file.",
)
@click.pass_context
def vault(ctx: click.Context, vault_path: Path) -> None:
    vault_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.obj = {"vault_path": vault_path}


@vault.command("init", help="Create a new empty vault.")
@click.pass_context
def vault_init(ctx: click.Context) -> None:
    path = ctx.obj["vault_path"]
    if path.exists():
        click.echo(f"vault already exists at {path}", err=True)
        sys.exit(1)
    pin = click.prompt("Set PIN (>=6 digits)", hide_input=True, confirmation_prompt=True)
    v = Vault(path)
    v.create(pin=pin)
    click.echo(f"created {path}")


@vault.command("add", help="Add a wallet from a mnemonic supplied on stdin.")
@click.option("--label", required=True, help="Human-readable label for the wallet.")
@click.pass_context
def vault_add(ctx: click.Context, label: str) -> None:
    path = ctx.obj["vault_path"]
    if not path.exists():
        click.echo("vault does not exist; run `piwallet vault init` first", err=True)
        sys.exit(1)
    pin = click.prompt("PIN", hide_input=True)
    phrase = click.get_text_stream("stdin").read().strip()
    v = Vault(path)
    try:
        rec = v.add_wallet(pin=pin, mnemonic_phrase=phrase, label=label)
    except WrongPinError as exc:
        click.echo(f"WRONG PIN ({exc.attempts_remaining} attempts left)", err=True)
        sys.exit(2)
    except VaultWipedError as exc:
        click.echo(f"VAULT WIPED: {exc}", err=True)
        sys.exit(3)
    except (VaultError, mnem.MnemonicError) as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)
    click.echo(f"added wallet '{rec.label}' id={rec.id} fp={rec.fingerprint.hex()}")


@vault.command("list", help="List wallets in this vault (no PIN required).")
@click.pass_context
def vault_list(ctx: click.Context) -> None:
    path = ctx.obj["vault_path"]
    if not path.exists():
        click.echo(f"no vault at {path}")
        return
    v = Vault(path)
    for w in v.list_wallets():
        click.echo(
            f"{w.id}\t{w.fingerprint.hex()}\t{w.label}\t"
            f"{w.derivation_path}\t{w.word_count} words\t{w.created_at}"
        )


@vault.command("export-xpub", help="Print the account xpub for a wallet.")
@click.argument("wallet_id")
@click.pass_context
def vault_export_xpub(ctx: click.Context, wallet_id: str) -> None:
    path = ctx.obj["vault_path"]
    pin = click.prompt("PIN", hide_input=True)
    v = Vault(path)
    try:
        click.echo(v.get_account_xpub(pin, wallet_id))
    except WrongPinError as exc:
        click.echo(f"WRONG PIN ({exc.attempts_remaining} left)", err=True)
        sys.exit(2)


# ---- envelope commands -------------------------------------------------


@main.command("decode", help="Decode any envelope blob and print a summary.")
@click.argument("blob_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def decode_cmd(blob_path: Path) -> None:
    blob = blob_path.read_bytes()
    try:
        decoded = env.decode(blob)
    except env.EnvelopeError as exc:
        click.echo(f"DECODE FAILED: {exc}", err=True)
        sys.exit(1)
    if isinstance(decoded, env.UnsignedProposal):
        click.echo(_summarize_proposal(decoded))
    elif isinstance(decoded, env.XpubExport):
        click.echo(_summarize_xpub_export(decoded))
    elif isinstance(decoded, env.SignedTx):
        click.echo(_summarize_signed(decoded))


# ---- sign command ------------------------------------------------------


@main.command(
    "sign",
    help="Verify and sign an unsigned_proposal blob, emitting a SignedTx blob.",
)
@click.argument("proposal_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--vault-path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path.home() / ".piwallet-dev" / "vault.bin",
    show_default=True,
)
@click.option("--wallet-id", required=True, help="Wallet to sign with.")
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Where to write the signed_tx envelope (default: stdout, hex-encoded).",
)
@click.option(
    "--max-fee-rate-satskb",
    type=int,
    default=10_000,
    show_default=True,
    help="Reject proposals whose feeRate exceeds this cap.",
)
def sign_cmd(
    proposal_path: Path,
    vault_path: Path,
    wallet_id: str,
    output: Path | None,
    max_fee_rate_satskb: int,
) -> None:
    blob = proposal_path.read_bytes()
    try:
        proposal = env.decode(blob)
    except env.EnvelopeError as exc:
        click.echo(f"DECODE FAILED: {exc}", err=True)
        sys.exit(1)
    if not isinstance(proposal, env.UnsignedProposal):
        click.echo(f"expected unsigned_proposal, got {type(proposal).__name__}", err=True)
        sys.exit(1)

    pin = click.prompt("PIN", hide_input=True)
    v = Vault(vault_path)
    if not v.is_initialized:
        click.echo(f"no vault at {vault_path}; run `piwallet vault init`", err=True)
        sys.exit(1)

    # Confirm the wallet's xpub matches the proposal's wallet_fp.
    try:
        xpub_str = v.get_account_xpub(pin, wallet_id)
    except WrongPinError as exc:
        click.echo(f"WRONG PIN ({exc.attempts_remaining} left)", err=True)
        sys.exit(2)
    except VaultWipedError as exc:
        click.echo(f"VAULT WIPED: {exc}", err=True)
        sys.exit(3)

    fp = deriv.key_fingerprint(deriv.parse_xpub(xpub_str))
    if fp != proposal.wallet_fp:
        click.echo(
            f"FINGERPRINT MISMATCH: vault wallet fp={fp.hex()} but "
            f"proposal addresses fp={proposal.wallet_fp.hex()}",
            err=True,
        )
        sys.exit(1)

    derive_key = partial(v.derive_signing_key, pin, wallet_id)

    try:
        result = sgn.verify_then_sign(
            proposal,
            xpub_str,
            derive_key,
            max_fee_rate_satskb=max_fee_rate_satskb,
        )
    except vfy.ProposalVerificationError as exc:
        click.echo(f"VERIFY FAILED: {exc}", err=True)
        sys.exit(4)
    except sgn.SigningError as exc:
        click.echo(f"SIGN FAILED: {exc}", err=True)
        sys.exit(5)

    click.echo(
        f"verified: in={result.verified.total_in} "
        f"out={result.verified.total_out} fee={result.fee_sats}",
        err=True,
    )
    click.echo(f"txid: {result.txid}", err=True)

    signed_envelope = sgn.to_signed_envelope(result, wallet_fp=fp)
    signed_blob = env.encode(signed_envelope)
    if output is None:
        sys.stdout.buffer.write(signed_blob)
    else:
        output.write_bytes(signed_blob)
        click.echo(f"wrote signed envelope to {output}", err=True)


# ---- summary helpers ---------------------------------------------------


def _summarize_proposal(p: env.UnsignedProposal) -> str:
    total_in = sum(i.sats for i in p.inputs)
    total_out = sum(o.sats for o in p.outputs)
    lines = [
        f"kind: unsigned_proposal v={env.ENVELOPE_VERSION}",
        f"walletFp: {p.wallet_fp.hex()}",
        f"inputs: {len(p.inputs)} (claimed total {total_in} sat)",
        f"outputs: {len(p.outputs)} (total {total_out} sat)",
        f"changeIndex: {p.change_index}  changeDerivation: {p.change_derivation}",
        f"feeRate: {p.fee_rate_satskb} sat/kb  locktime: {p.locktime}",
        f"headerAnchors: {sorted(p.header_anchors.keys())}",
    ]
    return "\n".join(lines)


def _summarize_xpub_export(x: env.XpubExport) -> str:
    return "\n".join(
        [
            f"kind: xpub_export v={env.ENVELOPE_VERSION}",
            f"label: {x.label}",
            f"path: {x.path}",
            f"fingerprint: {x.fingerprint.hex()}",
            f"xpub: {x.xpub}",
        ]
    )


def _summarize_signed(s: env.SignedTx) -> str:
    return "\n".join(
        [
            f"kind: signed_tx v={env.ENVELOPE_VERSION}",
            f"walletFp: {s.wallet_fp.hex()}",
            f"txid: {s.txid}",
            f"raw size: {len(s.raw_hex) // 2} bytes",
        ]
    )


if __name__ == "__main__":
    main()

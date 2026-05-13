"""PiWalletSV CLI: dev-time interface to the offline core.

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
from piwallet.qr.multipart import (
    MultipartAssembler,
    MultipartQrError,
    split_envelope_to_lines,
)


@click.group(help="PiWalletSV offline signing CLI.")
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


# ---- pairing -----------------------------------------------------------


@main.command(
    "xpub-export",
    help="Build an xpub_export envelope (CBOR+gzip) for QR pairing with the PWA.",
)
@click.option(
    "--vault-path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path.home() / ".piwallet-dev" / "vault.bin",
    show_default=True,
)
@click.option("--wallet-id", required=True, help="Wallet id to export.")
@click.option(
    "--label",
    help="Override the stored label in the emitted envelope (defaults to the vault label).",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Where to write the envelope blob (default: stdout, raw bytes).",
)
def xpub_export_cmd(
    vault_path: Path,
    wallet_id: str,
    label: str | None,
    output: Path | None,
) -> None:
    """Wrap the wallet's account xpub in a versioned `xpub_export` envelope."""

    v = Vault(vault_path)
    if not v.is_initialized:
        click.echo(
            f"no vault at {vault_path}; run `piwallet vault init` first",
            err=True,
        )
        sys.exit(1)

    rec = next((w for w in v.list_wallets() if w.id == wallet_id), None)
    if rec is None:
        click.echo(f"no wallet with id={wallet_id} in vault", err=True)
        sys.exit(1)

    pin = click.prompt("PIN", hide_input=True)
    try:
        xpub_str = v.get_account_xpub(pin, wallet_id)
    except WrongPinError as exc:
        click.echo(f"WRONG PIN ({exc.attempts_remaining} left)", err=True)
        sys.exit(2)
    except VaultWipedError as exc:
        click.echo(f"VAULT WIPED: {exc}", err=True)
        sys.exit(3)

    payload = env.XpubExport(
        xpub=xpub_str,
        path=rec.derivation_path,
        label=label if label is not None else rec.label,
        fingerprint=rec.fingerprint,
    )
    blob = env.encode(payload)

    if output is None:
        sys.stdout.buffer.write(blob)
    else:
        output.write_bytes(blob)
        click.echo(
            f"wrote {len(blob)} bytes (xpub_export, fp={rec.fingerprint.hex()}) to {output}",
            err=True,
        )


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


# ---- multipart QR (camera / animated codes) ----------------------------


@main.group(help="Multipart QR ingest (animated codes from the companion PWA).")
def qr() -> None:
    pass


@qr.command("join", help="Assemble PW1 lines from stdin into one binary blob.")
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write raw bytes here; default: stdout.",
)
def qr_join(output: Path | None) -> None:
    """Read text lines; only lines starting with ``PW1|`` are consumed."""

    asm = MultipartAssembler()
    stdin = click.get_text_stream("stdin")
    for line in stdin:
        s = line.strip()
        if not s.startswith("PW1|"):
            continue
        try:
            done = asm.feed(s)
        except MultipartQrError as exc:
            click.echo(f"QR ASSEMBLY ERROR: {exc}", err=True)
            sys.exit(1)
        if done is not None:
            if output is not None:
                output.write_bytes(done)
                click.echo(f"wrote {len(done)} bytes to {output}", err=True)
            else:
                sys.stdout.buffer.write(done)
            sys.exit(0)

    click.echo("incomplete: never received a full PW1 set", err=True)
    sys.exit(1)


@qr.command(
    "split",
    help="Split a binary blob into PW1 lines on stdout (mirror of `qr join`).",
)
@click.argument(
    "input_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=False,
)
@click.option(
    "-c",
    "--chunk-chars",
    type=click.IntRange(min=64),
    default=720,
    show_default=True,
    help="Max encoded chunk characters per QR frame (>=64).",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write PW1 lines here (default: stdout).",
)
def qr_split(input_path: Path | None, chunk_chars: int, output: Path | None) -> None:
    """Read raw envelope bytes and emit one ``PW1|<total>|<index>|...`` line per QR frame.

    Pipes well with ``qrencode`` for a quick terminal pairing demo:

    \b
        piwallet xpub-export --wallet-id <id> | piwallet qr split | \\
            while read line; do clear; qrencode -t UTF8 "$line"; sleep 0.4; done
    """

    if input_path is None:
        data = sys.stdin.buffer.read()
    else:
        data = input_path.read_bytes()

    try:
        lines = split_envelope_to_lines(data, max_encoded_chunk_chars=chunk_chars)
    except ValueError as exc:
        click.echo(f"split error: {exc}", err=True)
        sys.exit(1)

    body = "\n".join(lines) + "\n"
    if output is None:
        click.echo(body, nl=False)
    else:
        output.write_text(body)
        click.echo(
            f"wrote {len(lines)} PW1 line(s) ({len(data)} bytes) to {output}",
            err=True,
        )


@qr.command("scan-camera", help="Capture QR frames until a full PW1 payload is assembled (Pi).")
@click.option("--size", default="1280x960", show_default=True, help="Capture resolution WxH.")
@click.option(
    "--interval",
    type=float,
    default=0.35,
    show_default=True,
    help="Sleep between frames (seconds).",
)
@click.option(
    "--af",
    "autofocus",
    type=click.Choice(["continuous", "auto", "manual"]),
    default="continuous",
    show_default=True,
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write assembled raw bytes (same as `envelope.encode` output).",
)
@click.option(
    "--show/--no-show",
    default=True,
    help="Print decoded envelope summary to stderr when done.",
)
def qr_scan_camera(
    size: str,
    interval: float,
    autofocus: str,
    output: Path | None,
    show: bool,
) -> None:
    """Requires Pi camera stack (picamera2) and pyzbar."""

    def on_progress(_have: int, msg: str) -> None:
        click.echo(f"[scan] {msg}", err=True)

    from piwallet.qr.camera_scan import scan_multipart_from_camera

    try:
        blob = scan_multipart_from_camera(
            size=size,
            interval_s=interval,
            autofocus=autofocus,
            on_progress=on_progress,
        )
    except MultipartQrError as exc:
        click.echo(f"QR ASSEMBLY ERROR: {exc}", err=True)
        sys.exit(1)
    except RuntimeError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    except KeyboardInterrupt:
        click.echo("aborted", err=True)
        sys.exit(130)

    if output is not None:
        output.write_bytes(blob)
        click.echo(f"wrote {len(blob)} bytes to {output}", err=True)

    if show:
        try:
            decoded = env.decode(blob)
            if isinstance(decoded, env.UnsignedProposal):
                click.echo(_summarize_proposal(decoded), err=True)
            elif isinstance(decoded, env.XpubExport):
                click.echo(_summarize_xpub_export(decoded), err=True)
            elif isinstance(decoded, env.SignedTx):
                click.echo(_summarize_signed(decoded), err=True)
            else:
                click.echo(f"unknown envelope type: {type(decoded)}", err=True)
        except env.EnvelopeError as exc:
            click.echo(f"DECODE FAILED: {exc}", err=True)
            if output is None:
                sys.stdout.buffer.write(blob)
            sys.exit(1)

    if output is None and not show:
        sys.stdout.buffer.write(blob)


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


# ---- first-boot disclaimer ---------------------------------------------


@main.group(help="First-boot disclaimer acceptance.")
def firstboot() -> None:
    pass


@firstboot.command("status", help="Print the saved disclaimer acceptance state.")
@click.option(
    "--state-path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path to the terms state file. Defaults to ~/.piwallet-dev/terms.json.",
)
def firstboot_status(state_path: Path | None) -> None:
    from piwallet.firstboot.terms import (
        CURRENT_TERMS_VERSION,
        load_state,
        requires_acceptance,
    )

    state = load_state(state_path)
    if state is None:
        click.echo(
            f"no acceptance on file; current version is v{CURRENT_TERMS_VERSION}",
        )
        sys.exit(1)
    click.echo(f"accepted version : v{state.terms_version}")
    click.echo(f"current version  : v{CURRENT_TERMS_VERSION}")
    click.echo(f"accepted at      : {state.accepted_at}")
    click.echo(f"device id        : {state.device_id}")
    if requires_acceptance(state_path):
        click.echo("STALE: this device must re-accept the current disclaimer.")
        sys.exit(1)


@firstboot.command("run", help="Run the disclaimer flow on the bonnet (or headless).")
@click.option(
    "--state-path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path to the terms state file. Defaults to ~/.piwallet-dev/terms.json.",
)
@click.option(
    "--display",
    type=click.Choice(["auto", "st7789", "headless"]),
    default="auto",
    show_default=True,
)
@click.option(
    "--input",
    "input_backend",
    type=click.Choice(["auto", "bonnet", "fake"]),
    default="auto",
    show_default=True,
)
@click.option(
    "--force",
    is_flag=True,
    help="Run even if the current version is already accepted.",
)
def firstboot_run(
    state_path: Path | None,
    display: str,
    input_backend: str,
    force: bool,
) -> None:
    from piwallet.firstboot.disclaimer import DisclaimerScreen
    from piwallet.firstboot.terms import mark_accepted, requires_acceptance
    from piwallet.ui.app import IdleWakeTracker, make_input_manager, run_screen
    from piwallet.ui.display import open_display
    from piwallet.ui.input import open_input

    if not force and not requires_acceptance(state_path):
        click.echo("disclaimer already accepted; use --force to re-run.")
        return

    disp = open_display(display)
    inp = open_input(input_backend)
    mgr = make_input_manager(inp)
    idle = IdleWakeTracker(mgr)
    screen = DisclaimerScreen()
    result = run_screen(disp, mgr, screen, idle_wake=idle)
    if result is True:
        state = mark_accepted(state_path)
        click.echo(f"accepted v{state.terms_version} at {state.accepted_at}")
    else:
        click.echo("disclaimer NOT accepted; aborting.", err=True)
        sys.exit(1)


@main.command("bonnet", help="Run the full bonnet boot loop on the device.")
@click.option(
    "--vault-path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path.home() / ".piwallet-dev" / "vault.bin",
    show_default=True,
)
@click.option(
    "--terms-path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Override the disclaimer state file. Defaults to ~/.piwallet-dev/terms.json.",
)
@click.option(
    "--settings-path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Override the global settings file. Defaults to ~/.piwallet-dev/settings.json.",
)
@click.option(
    "--display",
    type=click.Choice(["auto", "st7789", "headless"]),
    default="auto",
    show_default=True,
)
@click.option(
    "--input",
    "input_backend",
    type=click.Choice(["auto", "bonnet", "fake"]),
    default="auto",
    show_default=True,
)
@click.option(
    "--fps",
    type=click.IntRange(5, 120),
    default=30,
    show_default=True,
    help="Target frame rate for the bonnet main loop.",
)
def bonnet_cmd(
    vault_path: Path,
    terms_path: Path | None,
    settings_path: Path | None,
    display: str,
    input_backend: str,
    fps: int,
) -> None:
    """Boot the bonnet UI: disclaimer -> PIN unlock -> wallet list -> detail."""
    from piwallet.bonnet.app import run_bonnet
    from piwallet.ui.app import make_input_manager
    from piwallet.ui.display import open_display
    from piwallet.ui.input import open_input

    disp = open_display(display)
    inp = open_input(input_backend)
    mgr = make_input_manager(inp)
    code = run_bonnet(
        vault_path=vault_path,
        display=disp,
        input_mgr=mgr,
        terms_path=terms_path,
        settings_path=settings_path,
        target_fps=fps,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()

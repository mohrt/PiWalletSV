"""End-to-end CLI smoke test.

Drives the `piwallet` Click app in-process via `CliRunner` to confirm that
the full pipeline -- vault init -> add wallet -> sign fixture proposal --
produces a parseable signed_tx envelope.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from piwallet.cli import main
from piwallet.core import envelope as env
from piwallet.qr.multipart import join_multipart_lines, split_envelope_to_lines
from tests.fixtures.generate_fixtures import (
    CANONICAL_MNEMONIC,
    PROPOSAL_PATH,
    build_proposal_01,
)

PIN = "654321"


def test_full_sign_pipeline(tmp_path: Path) -> None:
    runner = CliRunner()
    vault_path = tmp_path / "vault.bin"

    # 1) init vault (PIN entered twice for confirmation)
    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "init"],
        input=f"{PIN}\n{PIN}\n",
    )
    assert res.exit_code == 0, res.output
    assert vault_path.exists()

    # 2) add wallet from canonical mnemonic
    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "add", "--label", "test"],
        input=f"{PIN}\n{CANONICAL_MNEMONIC}\n",
    )
    assert res.exit_code == 0, res.output
    assert "fp=cf987d8c" in res.output

    # 3) list wallets to capture wallet id
    res = runner.invoke(main, ["vault", "--vault-path", str(vault_path), "list"])
    assert res.exit_code == 0, res.output
    wallet_id = res.output.split()[0]
    assert len(wallet_id) == 36  # uuid

    # 4) sign the canonical fixture
    signed_path = tmp_path / "signed.cbor"
    res = runner.invoke(
        main,
        [
            "sign",
            "--vault-path",
            str(vault_path),
            "--wallet-id",
            wallet_id,
            "-o",
            str(signed_path),
            str(PROPOSAL_PATH),
        ],
        input=f"{PIN}\n",
    )
    assert res.exit_code == 0, res.output
    assert signed_path.exists()

    # 5) decode the signed envelope
    decoded = env.decode(signed_path.read_bytes())
    assert isinstance(decoded, env.SignedTx)
    assert decoded.wallet_fp.hex() == "cf987d8c"
    assert decoded.txid

    # Repeating the exact legacy proposal after a restart must replay the
    # durable response byte-for-byte instead of making another signature.
    replay_path = tmp_path / "signed-replayed.cbor"
    replay = runner.invoke(
        main,
        [
            "sign",
            "--vault-path",
            str(vault_path),
            "--wallet-id",
            wallet_id,
            "-o",
            str(replay_path),
            str(PROPOSAL_PATH),
        ],
        input=f"{PIN}\n",
    )
    assert replay.exit_code == 0, replay.output
    assert "replayed persisted signed response" in replay.output
    assert replay_path.read_bytes() == signed_path.read_bytes()


def test_sign_hex_in_hex_out_round_trip(tmp_path: Path) -> None:
    """Hex-bridge SSH workflow: --hex input + hex on stdout decode cleanly.

    The wallet-detail card on the companion will surface the unsigned
    proposal as a hex string for copy-paste over SSH, and the operator
    will paste the resulting hex from `piwallet sign` back into the
    companion's broadcast page. This test pins both ends of that
    contract:

    * `--hex <hex>` decodes a hex-encoded proposal correctly,
    * stdout (no `-o`) is a single hex line that round-trips through
      ``bytes.fromhex`` and ``env.decode`` to a valid `SignedTx`.

    Whitespace tolerance (the companion textarea wraps every 64 chars)
    is exercised with a synthetic newline mid-payload — the CLI should
    strip it before decoding.
    """
    runner = CliRunner()
    vault_path = tmp_path / "vault.bin"

    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "init"],
        input=f"{PIN}\n{PIN}\n",
    )
    assert res.exit_code == 0

    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "add", "--label", "hex-bridge"],
        input=f"{PIN}\n{CANONICAL_MNEMONIC}\n",
    )
    assert res.exit_code == 0

    res = runner.invoke(main, ["vault", "--vault-path", str(vault_path), "list"])
    wallet_id = res.output.split()[0]

    proposal_hex = PROPOSAL_PATH.read_bytes().hex()
    # Inject a newline halfway through to mimic the line-wrapped paste a
    # 64-col copy-paste would produce; the CLI must tolerate this.
    mid = len(proposal_hex) // 2
    wrapped_hex = proposal_hex[:mid] + "\n" + proposal_hex[mid:]

    res = runner.invoke(
        main,
        [
            "sign",
            "--vault-path",
            str(vault_path),
            "--wallet-id",
            wallet_id,
            "--hex",
            wrapped_hex,
        ],
        input=f"{PIN}\n",
    )
    assert res.exit_code == 0, res.output
    # stdout should now be a single hex line. The summary lines go to
    # stderr; with CliRunner those are merged into `output`, so we look
    # for the hex line specifically — the longest line consisting only
    # of hex chars is the signed_tx blob.
    candidates = [ln.strip() for ln in res.output.splitlines() if ln.strip()]
    hex_lines = [
        ln for ln in candidates if len(ln) >= 32 and all(c in "0123456789abcdef" for c in ln)
    ]
    assert hex_lines, f"no hex line in output: {res.output!r}"
    signed_blob = bytes.fromhex(hex_lines[-1])
    decoded = env.decode(signed_blob)
    assert isinstance(decoded, env.SignedTx)
    assert decoded.wallet_fp.hex() == "cf987d8c"
    assert decoded.txid


def test_sign_tty_stdout_is_label_prefixed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When stdout is a TTY, the signed_tx hex is prefixed `signed_tx: `.

    Pipelines (`piwallet sign … | xclip`) still get bare hex — that's
    pinned by `test_sign_hex_in_hex_out_round_trip` which runs under
    CliRunner's default StringIO stdout (isatty == False). This test
    forces the TTY branch by monkey-patching the
    ``piwallet.cli._stdout_is_tty`` predicate, mirroring what an
    interactive SSH session sees:

        verified: in=99904 out=99791 fee=113
        txid: f9c9f9229f...
        signed_tx: 1f8b08...

    Without a label the txid line and the hex blob visually run
    together when copy-pasted, which is the bug this prefix fixes.
    """
    monkeypatch.setattr("piwallet.cli._stdout_is_tty", lambda: True)

    runner = CliRunner()
    vault_path = tmp_path / "vault.bin"

    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "init"],
        input=f"{PIN}\n{PIN}\n",
    )
    assert res.exit_code == 0, res.output
    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "add", "--label", "tty"],
        input=f"{PIN}\n{CANONICAL_MNEMONIC}\n",
    )
    assert res.exit_code == 0, res.output
    res = runner.invoke(main, ["vault", "--vault-path", str(vault_path), "list"])
    wallet_id = res.output.split()[0]

    res = runner.invoke(
        main,
        [
            "sign",
            "--vault-path",
            str(vault_path),
            "--wallet-id",
            wallet_id,
            str(PROPOSAL_PATH),
        ],
        input=f"{PIN}\n",
    )
    assert res.exit_code == 0, res.output

    label_lines = [ln for ln in res.output.splitlines() if ln.startswith("signed_tx: ")]
    assert label_lines, f"no labelled line in TTY-mode output: {res.output!r}"
    hex_part = label_lines[-1].removeprefix("signed_tx: ").strip()
    # The hex portion after the prefix must round-trip cleanly.
    assert hex_part, "label was emitted but hex was empty"
    assert all(c in "0123456789abcdef" for c in hex_part), (
        f"non-hex chars after prefix: {hex_part!r}"
    )
    decoded = env.decode(bytes.fromhex(hex_part))
    assert isinstance(decoded, env.SignedTx)
    assert decoded.wallet_fp.hex() == "cf987d8c"
    assert decoded.txid


def test_sign_rejects_both_file_and_hex(tmp_path: Path) -> None:
    """Providing *both* a positional file and --hex is ambiguous and should fail.

    The check is a guard against operators who copy a `--hex` example
    from docs but forget to remove the file path from a previous
    invocation; without this branch, the file would silently win and
    the hex paste would be ignored.
    """
    runner = CliRunner()
    vault_path = tmp_path / "vault.bin"
    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "init"],
        input=f"{PIN}\n{PIN}\n",
    )
    assert res.exit_code == 0
    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "add", "--label", "x"],
        input=f"{PIN}\n{CANONICAL_MNEMONIC}\n",
    )
    assert res.exit_code == 0
    wid = runner.invoke(main, ["vault", "--vault-path", str(vault_path), "list"]).output.split()[0]

    res = runner.invoke(
        main,
        [
            "sign",
            "--vault-path",
            str(vault_path),
            "--wallet-id",
            wid,
            "--hex",
            "deadbeef",
            str(PROPOSAL_PATH),
        ],
    )
    assert res.exit_code != 0
    assert "exactly one of" in res.output


def test_sign_rejects_neither_file_nor_hex(tmp_path: Path) -> None:
    """Calling sign with neither a file nor --hex must error cleanly."""
    runner = CliRunner()
    vault_path = tmp_path / "vault.bin"
    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "init"],
        input=f"{PIN}\n{PIN}\n",
    )
    assert res.exit_code == 0
    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "add", "--label", "x"],
        input=f"{PIN}\n{CANONICAL_MNEMONIC}\n",
    )
    assert res.exit_code == 0
    wid = runner.invoke(main, ["vault", "--vault-path", str(vault_path), "list"]).output.split()[0]

    res = runner.invoke(
        main,
        [
            "sign",
            "--vault-path",
            str(vault_path),
            "--wallet-id",
            wid,
        ],
    )
    assert res.exit_code != 0
    assert "exactly one of" in res.output


def test_sign_rejects_invalid_hex(tmp_path: Path) -> None:
    """An odd-length or non-hex --hex value must abort with a clear message."""
    runner = CliRunner()
    vault_path = tmp_path / "vault.bin"
    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "init"],
        input=f"{PIN}\n{PIN}\n",
    )
    assert res.exit_code == 0
    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "add", "--label", "x"],
        input=f"{PIN}\n{CANONICAL_MNEMONIC}\n",
    )
    assert res.exit_code == 0
    wid = runner.invoke(main, ["vault", "--vault-path", str(vault_path), "list"]).output.split()[0]

    # Odd length
    res = runner.invoke(
        main,
        [
            "sign",
            "--vault-path",
            str(vault_path),
            "--wallet-id",
            wid,
            "--hex",
            "abc",
        ],
    )
    assert res.exit_code != 0
    assert "odd length" in res.output

    # Non-hex chars
    res = runner.invoke(
        main,
        [
            "sign",
            "--vault-path",
            str(vault_path),
            "--wallet-id",
            wid,
            "--hex",
            "zzzz",
        ],
    )
    assert res.exit_code != 0
    assert "invalid hex" in res.output


def test_sign_rejects_wrong_wallet_for_proposal(tmp_path: Path) -> None:
    """If the vault wallet's fingerprint != proposal.wallet_fp, sign aborts."""
    runner = CliRunner()
    vault_path = tmp_path / "vault.bin"

    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "init"],
        input=f"{PIN}\n{PIN}\n",
    )
    assert res.exit_code == 0

    other_phrase = "legal winner thank year wave sausage worth useful legal winner thank yellow"
    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "add", "--label", "other"],
        input=f"{PIN}\n{other_phrase}\n",
    )
    assert res.exit_code == 0

    res = runner.invoke(main, ["vault", "--vault-path", str(vault_path), "list"])
    wallet_id = res.output.split()[0]

    res = runner.invoke(
        main,
        [
            "sign",
            "--vault-path",
            str(vault_path),
            "--wallet-id",
            wallet_id,
            str(PROPOSAL_PATH),
        ],
        input=f"{PIN}\n",
    )
    assert res.exit_code != 0
    assert "FINGERPRINT MISMATCH" in res.output


def test_xpub_export_emits_decodable_envelope(tmp_path: Path) -> None:
    runner = CliRunner()
    vault_path = tmp_path / "vault.bin"

    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "init"],
        input=f"{PIN}\n{PIN}\n",
    )
    assert res.exit_code == 0, res.output

    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "add", "--label", "demo"],
        input=f"{PIN}\n{CANONICAL_MNEMONIC}\n",
    )
    assert res.exit_code == 0, res.output

    res = runner.invoke(main, ["vault", "--vault-path", str(vault_path), "list"])
    assert res.exit_code == 0
    wallet_id = res.output.split()[0]

    out_path = tmp_path / "xpub_export.bin"
    res = runner.invoke(
        main,
        [
            "xpub-export",
            "--vault-path",
            str(vault_path),
            "--wallet-id",
            wallet_id,
            "-o",
            str(out_path),
        ],
        input=f"{PIN}\n",
    )
    assert res.exit_code == 0, res.output
    assert out_path.exists()

    decoded = env.decode(out_path.read_bytes())
    assert isinstance(decoded, env.XpubExport)
    assert decoded.label == "demo"
    assert decoded.path == "m/44'/236'/0'"
    assert decoded.fingerprint.hex() == "cf987d8c"
    assert decoded.xpub.startswith("xpub")


def test_xpub_export_label_override(tmp_path: Path) -> None:
    runner = CliRunner()
    vault_path = tmp_path / "vault.bin"

    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "init"],
        input=f"{PIN}\n{PIN}\n",
    )
    assert res.exit_code == 0, res.output
    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "add", "--label", "stored-label"],
        input=f"{PIN}\n{CANONICAL_MNEMONIC}\n",
    )
    assert res.exit_code == 0, res.output
    res = runner.invoke(main, ["vault", "--vault-path", str(vault_path), "list"])
    wallet_id = res.output.split()[0]

    out_path = tmp_path / "xpub_export.bin"
    res = runner.invoke(
        main,
        [
            "xpub-export",
            "--vault-path",
            str(vault_path),
            "--wallet-id",
            wallet_id,
            "--label",
            "wire-label",
            "-o",
            str(out_path),
        ],
        input=f"{PIN}\n",
    )
    assert res.exit_code == 0, res.output

    decoded = env.decode(out_path.read_bytes())
    assert isinstance(decoded, env.XpubExport)
    assert decoded.label == "wire-label"


def test_decode_unsigned_fixture() -> None:
    runner = CliRunner()
    res = runner.invoke(main, ["decode", str(PROPOSAL_PATH)])
    assert res.exit_code == 0, res.output
    assert "unsigned_proposal" in res.output
    assert "walletFp: cf987d8c" in res.output
    # The v2 schema carries a ``headerAnchors`` map: one entry per
    # unique block referenced by the inputs' BUMP paths. The CLI
    # summary surfaces the count + height range so an operator can
    # sanity-check it against the explorer at decode time.
    assert "headerAnchors:" in res.output


def test_vault_list_renders_network_column(tmp_path: Path) -> None:
    """`vault list` distinguishes mainnet vs testnet wallets visually.

    Without this, an operator can't tell which records hold testnet
    keys from CLI output alone — the bonnet's wallet-info screen
    surfaces the network but the CLI is what scripts and backup
    monitors consume.
    """
    runner = CliRunner()
    vault_path = tmp_path / "vault.bin"

    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "init"],
        input=f"{PIN}\n{PIN}\n",
    )
    assert res.exit_code == 0, res.output

    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "add", "--label", "main-w"],
        input=f"{PIN}\n{CANONICAL_MNEMONIC}\n",
    )
    assert res.exit_code == 0, res.output

    other = "legal winner thank year wave sausage worth useful legal winner thank yellow"
    res = runner.invoke(
        main,
        [
            "vault",
            "--vault-path",
            str(vault_path),
            "add",
            "--label",
            "test-w",
            "--network",
            "test",
        ],
        input=f"{PIN}\n{other}\n",
    )
    assert res.exit_code == 0, res.output

    res = runner.invoke(main, ["vault", "--vault-path", str(vault_path), "list"])
    assert res.exit_code == 0, res.output

    main_line = next(line for line in res.output.splitlines() if "main-w" in line)
    test_line = next(line for line in res.output.splitlines() if "test-w" in line)
    # Tab-separated columns: id, fp, label, hd_path, network, words, created_at.
    assert "\tmainnet\t" in main_line
    assert "\tTESTNET\t" in test_line
    # Mainnet should not get the loud uppercase label and vice-versa.
    assert "\tTESTNET\t" not in main_line
    assert "\tmainnet\t" not in test_line


def test_vault_add_rejects_unknown_network(tmp_path: Path) -> None:
    """Click's choice validation refuses anything other than main/test."""
    runner = CliRunner()
    vault_path = tmp_path / "vault.bin"

    res = runner.invoke(
        main,
        ["vault", "--vault-path", str(vault_path), "init"],
        input=f"{PIN}\n{PIN}\n",
    )
    assert res.exit_code == 0

    res = runner.invoke(
        main,
        [
            "vault",
            "--vault-path",
            str(vault_path),
            "add",
            "--label",
            "regtest-w",
            "--network",
            "regtest",
        ],
        input=f"{PIN}\n{CANONICAL_MNEMONIC}\n",
    )
    assert res.exit_code != 0
    assert "regtest" in res.output  # Click echoes the rejected value


def test_mnemonic_new() -> None:
    runner = CliRunner()
    for n in (12, 24):
        res = runner.invoke(main, ["mnemonic", "new", "--words", str(n)])
        assert res.exit_code == 0
        assert len(res.output.strip().split()) == n


def test_mnemonic_validate_ok() -> None:
    runner = CliRunner()
    res = runner.invoke(main, ["mnemonic", "validate"], input=CANONICAL_MNEMONIC)
    assert res.exit_code == 0
    assert "OK" in res.output


def test_mnemonic_validate_bad() -> None:
    runner = CliRunner()
    res = runner.invoke(main, ["mnemonic", "validate"], input="not a real mnemonic")
    assert res.exit_code == 1
    assert "INVALID" in res.output


def test_qr_join_roundtrip(tmp_path: Path) -> None:
    runner = CliRunner()

    blob, _meta = build_proposal_01()
    lines = split_envelope_to_lines(blob, max_encoded_chunk_chars=120)
    stdin = "\n".join(lines[::-1]) + "\nnoise line\n" + "\n"

    out_path = tmp_path / "joined.bin"
    res = runner.invoke(main, ["qr", "join", "-o", str(out_path)], input=stdin)

    assert res.exit_code == 0, res.output
    assert out_path.read_bytes() == blob
    stdin = "\n".join(lines[::-1]) + "\nnoise line\n" + "\n"

    out_path = tmp_path / "joined.bin"
    res = runner.invoke(main, ["qr", "join", "-o", str(out_path)], input=stdin)

    assert res.exit_code == 0, res.output
    assert out_path.read_bytes() == blob


def test_qr_join_incomplete() -> None:
    runner = CliRunner()
    stdin = "PW1|3|0|aaa\n"
    res = runner.invoke(main, ["qr", "join"], input=stdin)
    assert res.exit_code == 1
    assert "incomplete" in res.output


def test_qr_split_roundtrips_with_join(tmp_path: Path) -> None:
    """`qr split` is the inverse of `qr join` byte-for-byte."""
    runner = CliRunner()

    blob, _meta = build_proposal_01()
    input_path = tmp_path / "proposal.bin"
    input_path.write_bytes(blob)

    res = runner.invoke(
        main,
        ["qr", "split", "--chunk-chars", "120", str(input_path)],
    )
    assert res.exit_code == 0, res.output
    lines = [line for line in res.output.splitlines() if line.startswith("PW1|")]
    assert len(lines) >= 2
    assert join_multipart_lines(lines) == blob


def test_qr_split_reads_stdin() -> None:
    runner = CliRunner()
    blob, _meta = build_proposal_01()
    res = runner.invoke(
        main,
        ["qr", "split", "--chunk-chars", "200"],
        input=blob.decode("latin-1"),  # CliRunner stdin is a text stream
    )
    # CliRunner's text-mode stdin won't preserve high bytes losslessly, so the
    # round-trip won't be byte-perfect; we just confirm we got PW1 lines.
    assert res.exit_code == 0, res.output
    lines = [line for line in res.output.splitlines() if line.startswith("PW1|")]
    assert len(lines) >= 1


def test_qr_split_output_file(tmp_path: Path) -> None:
    runner = CliRunner()
    blob, _meta = build_proposal_01()
    in_path = tmp_path / "in.bin"
    in_path.write_bytes(blob)
    out_path = tmp_path / "lines.txt"

    res = runner.invoke(
        main,
        ["qr", "split", "--chunk-chars", "120", "-o", str(out_path), str(in_path)],
    )
    assert res.exit_code == 0, res.output
    lines = [line for line in out_path.read_text().splitlines() if line.startswith("PW1|")]
    assert join_multipart_lines(lines) == blob


def test_qr_split_rejects_tiny_chunks() -> None:
    runner = CliRunner()
    res = runner.invoke(main, ["qr", "split", "--chunk-chars", "32"], input="ignored")
    assert res.exit_code != 0
    assert "32" in res.output or "48" in res.output or "64" in res.output

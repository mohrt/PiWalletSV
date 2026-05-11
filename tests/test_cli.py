"""End-to-end CLI smoke test.

Drives the `piwallet` Click app in-process via `CliRunner` to confirm that
the full pipeline -- vault init -> add wallet -> sign fixture proposal --
produces a parseable signed_tx envelope.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from piwallet.cli import main
from piwallet.core import envelope as env
from piwallet.qr.multipart import split_envelope_to_lines
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

    other_phrase = (
        "legal winner thank year wave sausage worth useful legal winner thank yellow"
    )
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


def test_decode_unsigned_fixture() -> None:
    runner = CliRunner()
    res = runner.invoke(main, ["decode", str(PROPOSAL_PATH)])
    assert res.exit_code == 0, res.output
    assert "unsigned_proposal" in res.output
    assert "walletFp: cf987d8c" in res.output
    assert "headerAnchors: [812345]" in res.output


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

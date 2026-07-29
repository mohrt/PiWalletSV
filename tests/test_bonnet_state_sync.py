"""Bonnet orchestration for verified wallet-state imports."""

from __future__ import annotations

from bsv import Transaction

from piwallet.bonnet import state_sync as flow
from piwallet.bonnet.sign_scan import ScanProposalScreen
from piwallet.core import atomic_beef
from piwallet.core import envelope as env
from piwallet.core.state import ZERO_STATE_HASH, WalletStateStore
from piwallet.core.vault import Vault
from piwallet.qr.multipart import join_multipart_lines
from piwallet.ui.display import HeadlessDisplay
from piwallet.ui.input import FakeInputBackend, InputManager
from piwallet.ui.pairing_multipart_qr_screen import PairingMultipartQrScreen
from tests.fixtures.generate_fixtures import CANONICAL_MNEMONIC, build_proposal_01

PIN = "123456"


def _fixture(tmp_path):
    vault = Vault(tmp_path / "vault.bin")
    vault.create(PIN)
    wallet = vault.add_wallet(PIN, CANONICAL_MNEMONIC, "state sync")
    proposal_blob, metadata = build_proposal_01()
    proposal = env.decode(proposal_blob)
    assert isinstance(proposal, env.UnsignedProposal)
    funding = Transaction.from_beef(proposal.inputs[0].beef)
    output = funding.outputs[proposal.inputs[0].vout]
    coin = env.StateCoin(
        txid=funding.txid(),
        vout=proposal.inputs[0].vout,
        sats=int(output.satoshis),
        locking_script=output.locking_script.hex(),
        derivation=proposal.inputs[0].derivation,
        status="confirmed",
        transaction_reference=funding.txid(),
        block_height=metadata["block_height"],
    )
    sync = env.StateSync(
        wallet_fp=wallet.fingerprint,
        request_id="bonnet-sync-1",
        expected_revision=0,
        expected_state_hash=ZERO_STATE_HASH,
        next_receive_index=1,
        next_change_index=0,
        coins=(env.StateSyncCoin(coin=coin, atomic_beef=atomic_beef.encode(funding)),),
        header_anchors=proposal.header_anchors,
    )
    return vault, wallet, sync


def test_valid_sync_is_committed_before_receipt_qr(tmp_path, monkeypatch) -> None:
    vault, wallet, sync = _fixture(tmp_path)
    receipts: list[env.StateReceipt] = []

    def fake_run_screen(_display, _input, screen, **_kwargs):
        if isinstance(screen, ScanProposalScreen):
            screen.result = env.encode(sync)
            return screen.result
        if isinstance(screen, PairingMultipartQrScreen):
            assert screen.title == "State secured"
            decoded = env.decode(join_multipart_lines(screen.pw1_frames))
            assert isinstance(decoded, env.StateReceipt)
            receipts.append(decoded)
            return "back"
        raise AssertionError(f"unexpected screen: {type(screen)!r}")

    monkeypatch.setattr(flow, "run_screen", fake_run_screen)
    result = flow.run_state_sync_flow(
        HeadlessDisplay(),
        InputManager(FakeInputBackend()),
        vault,
        PIN,
        wallet,
        start_worker=lambda _state: None,
        toast_seconds=0,
    )

    assert result == "stay"
    assert receipts[0].request_id == sync.request_id
    key = vault.derive_state_key(PIN, wallet.id)
    assert WalletStateStore(vault.state_path).load(wallet, key).revision == 1


def test_wrong_envelope_is_rejected_without_state_change(tmp_path, monkeypatch) -> None:
    vault, wallet, _sync = _fixture(tmp_path)
    wrong = env.XpubExport(
        xpub=vault.get_account_xpub(PIN, wallet.id),
        path=wallet.derivation_path,
        label=wallet.label,
        fingerprint=wallet.fingerprint,
        network=wallet.network,
    )
    modals: list[str] = []

    def fake_run_screen(_display, _input, screen, **_kwargs):
        assert isinstance(screen, ScanProposalScreen)
        screen.result = env.encode(wrong)
        return screen.result

    monkeypatch.setattr(flow, "run_screen", fake_run_screen)
    monkeypatch.setattr(
        flow,
        "_show_modal",
        lambda _display, **kwargs: modals.append(str(kwargs["title"])),
    )
    flow.run_state_sync_flow(
        HeadlessDisplay(),
        InputManager(FakeInputBackend()),
        vault,
        PIN,
        wallet,
        start_worker=lambda _state: None,
        toast_seconds=0,
    )

    assert modals == ["Sync failed"]
    key = vault.derive_state_key(PIN, wallet.id)
    assert WalletStateStore(vault.state_path).load(wallet, key).revision == 0


def test_cancel_returns_without_decoding(tmp_path, monkeypatch) -> None:
    vault, wallet, _sync = _fixture(tmp_path)

    def fake_run_screen(_display, _input, screen, **_kwargs):
        assert isinstance(screen, ScanProposalScreen)
        screen.result = "cancel"
        return screen.result

    monkeypatch.setattr(flow, "run_screen", fake_run_screen)
    assert (
        flow.run_state_sync_flow(
            HeadlessDisplay(),
            InputManager(FakeInputBackend()),
            vault,
            PIN,
            wallet,
            start_worker=lambda _state: None,
            toast_seconds=0,
        )
        == "stay"
    )

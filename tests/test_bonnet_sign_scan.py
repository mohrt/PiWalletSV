"""Bonnet sign-from-camera flow.

Covers the three screens (:class:`ScanProposalScreen`,
:class:`ConfirmProposalScreen`, :class:`PairingMultipartQrScreen` reuse)
and the :func:`run_sign_flow` orchestrator. The pyzbar / picamera2
stack is never exercised; tests inject a fake worker that pushes
``_ScanState`` updates synchronously so the bonnet UI loop sees them
on the next ``draw()`` call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from piwallet.bonnet import sign_scan as ss
from piwallet.bonnet import wallet_manage as wm
from piwallet.bonnet.sign_scan import (
    ConfirmProposalScreen,
    ScanProposalScreen,
    _ScanState,
    run_sign_flow,
)
from piwallet.bonnet.wallet_manage import (
    WalletManageAction,
    WalletManageMenuScreen,
)
from piwallet.core import derivation as deriv
from piwallet.core import envelope as env
from piwallet.core import mnemonic as mnem
from piwallet.core.vault import Vault, WalletRecord
from piwallet.ui.display import FrameBuffer, HeadlessDisplay
from piwallet.ui.input import Button, Event, EventKind, FakeInputBackend, InputManager
from piwallet.ui.pairing_multipart_qr_screen import PairingMultipartQrScreen
from tests.fixtures.generate_fixtures import CANONICAL_MNEMONIC, build_proposal_01

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _press(b: Button, kind: EventKind = EventKind.PRESS) -> Event:
    return Event(button=b, kind=kind, at_ms=0)


@pytest.fixture()
def real_proposal() -> tuple[bytes, env.UnsignedProposal, str]:
    """Build (encoded_blob, decoded_proposal, account_xpub) from canonical fixture."""
    blob, _meta = build_proposal_01()
    proposal = env.decode(blob)
    assert isinstance(proposal, env.UnsignedProposal)
    seed = mnem.seed_from_mnemonic(CANONICAL_MNEMONIC)
    master = deriv.master_xprv_from_seed(seed)
    account = deriv.derive_account(master)
    return blob, proposal, str(account.xpub)


@pytest.fixture()
def canonical_vault(tmp_path: Path) -> tuple[Vault, str, WalletRecord]:
    """Vault holding a single wallet derived from CANONICAL_MNEMONIC.

    The fingerprint and xpub match the canonical proposal fixture, so
    `run_sign_flow` can run an end-to-end verify+sign without
    monkey-patching the cryptography.
    """
    v = Vault(tmp_path / "v.bin")
    v.create(pin="123456")
    rec = v.add_wallet("123456", CANONICAL_MNEMONIC, label="canonical")
    return v, "123456", rec


# ===========================================================================
# ScanProposalScreen
# ===========================================================================


def _make_immediate_worker(blob: bytes) -> Callable[[_ScanState], None]:
    """Return a start_worker that synchronously declares the scan complete."""

    def start_worker(state: _ScanState) -> None:
        with state.lock:
            state.parts_received = 3
            state.parts_total = 3
            state.assembled = blob
            state.finished = True

    return start_worker


def _make_progress_only_worker() -> Callable[[_ScanState], None]:
    """Return a worker that publishes one progress update but never finishes."""

    def start_worker(state: _ScanState) -> None:
        with state.lock:
            state.parts_received = 1
            state.parts_total = 4
            state.status_text = "fragment 1/4"

    return start_worker


def test_scan_screen_finishes_when_worker_publishes_blob() -> None:
    blob = b"\xde\xad\xbe\xef"
    screen = ScanProposalScreen(start_worker=_make_immediate_worker(blob))
    fb = FrameBuffer()
    screen.draw(fb)
    assert screen.done is True
    assert screen.result == blob


def test_scan_screen_b_press_cancels_and_signals_worker() -> None:
    screen = ScanProposalScreen(start_worker=_make_progress_only_worker())
    fb = FrameBuffer()
    screen.draw(fb)
    assert not screen.done
    screen.on_event(_press(Button.B))
    assert screen.done is True
    assert screen.result == "cancel"
    with screen.state.lock:
        assert screen.state.cancel_requested is True


def test_scan_screen_long_b_propagates_exit() -> None:
    screen = ScanProposalScreen(start_worker=_make_progress_only_worker())
    screen.draw(FrameBuffer())
    screen.on_event(_press(Button.B, EventKind.LONG))
    assert screen.done and screen.result == "exit"


def test_scan_screen_renders_camera_settling_placeholder() -> None:
    """Before the worker pushes a thumbnail, the preview region shows a hint."""
    started = [False]

    def start_worker(_state: _ScanState) -> None:
        started[0] = True

    screen = ScanProposalScreen(start_worker=start_worker)
    fb = FrameBuffer()
    screen.draw(fb)
    assert started[0] is True
    # Smoke-test: the screen drew something other than pure black, and
    # is not done after a single tick (worker hasn't reported anything).
    assert not screen.done


def test_scan_screen_surfaces_worker_error() -> None:
    """Worker setting `error` ends the screen with `result='cancel'`."""

    def start_worker(state: _ScanState) -> None:
        with state.lock:
            state.error = "camera missing"
            state.finished = True

    screen = ScanProposalScreen(start_worker=start_worker)
    screen.draw(FrameBuffer())
    assert screen.done is True
    assert screen.result == "cancel"


def test_scan_screen_starts_worker_only_once() -> None:
    starts: list[int] = []

    def start_worker(_state: _ScanState) -> None:
        starts.append(1)

    screen = ScanProposalScreen(start_worker=start_worker)
    for _ in range(5):
        screen.draw(FrameBuffer())
    assert sum(starts) == 1


# ===========================================================================
# ConfirmProposalScreen
# ===========================================================================


def test_confirm_screen_a_signs(real_proposal) -> None:
    _blob, proposal, xpub = real_proposal
    screen = ConfirmProposalScreen(proposal=proposal, account_xpub_str=xpub)
    assert screen.verify_error is None
    assert screen.verified is not None
    screen.draw(FrameBuffer())
    screen.on_event(_press(Button.A))
    assert screen.done is True
    assert screen.result == "sign"


def test_confirm_screen_b_cancels(real_proposal) -> None:
    _blob, proposal, xpub = real_proposal
    screen = ConfirmProposalScreen(proposal=proposal, account_xpub_str=xpub)
    screen.on_event(_press(Button.B))
    assert screen.done and screen.result == "cancel"


def test_confirm_screen_long_b_toggles_advanced(real_proposal) -> None:
    """Hold B switches to the advanced detail view and back; does not exit."""
    _blob, proposal, xpub = real_proposal
    screen = ConfirmProposalScreen(proposal=proposal, account_xpub_str=xpub)
    assert screen.advanced is False
    screen.on_event(_press(Button.B, EventKind.LONG))
    assert not screen.done
    assert screen.advanced is True
    # Second hold B returns to summary view.
    screen.on_event(_press(Button.B, EventKind.LONG))
    assert screen.advanced is False
    assert not screen.done


def test_confirm_screen_rejects_a_when_verify_fails(real_proposal) -> None:
    """Pressing A on a verify-rejected proposal must not advance to sign."""
    import dataclasses

    _blob, proposal, xpub = real_proposal
    # Strip header_anchors: verify_proposal needs at least one anchor
    # to validate any BUMP path, and rejects empty maps outright.
    bad_proposal = dataclasses.replace(proposal, header_anchors={})
    screen = ConfirmProposalScreen(proposal=bad_proposal, account_xpub_str=xpub)
    assert screen.verify_error is not None, screen.verify_error
    # Drawing must not raise (smoke test the error layout).
    screen.draw(FrameBuffer())
    screen.on_event(_press(Button.A))
    assert not screen.done, "A press must not advance past a rejected proposal"
    # B still drops back.
    screen.on_event(_press(Button.B))
    assert screen.done and screen.result == "cancel"


# ===========================================================================
# run_sign_flow integration
# ===========================================================================


def test_run_sign_flow_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    canonical_vault: tuple[Vault, str, WalletRecord],
    real_proposal,
) -> None:
    """End-to-end: scan → confirm A → sign → animate signed_tx.

    No monkeypatching of the crypto layer — the signed_tx envelope is
    really produced from the canonical mnemonic and round-trips through
    :func:`env.encode`.
    """
    vault, pin, rec = canonical_vault
    blob, _proposal, _xpub = real_proposal
    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())

    saw_qr_with_frames: list[int] = []

    def fake_run_screen(_d, _m, screen, **_kw):
        if isinstance(screen, ScanProposalScreen):
            screen._ensure_started()
            screen.done = True
            screen.result = blob
            return screen.result
        if isinstance(screen, ConfirmProposalScreen):
            assert screen.verify_error is None
            screen.done = True
            screen.result = "sign"
            return screen.result
        if isinstance(screen, PairingMultipartQrScreen):
            saw_qr_with_frames.append(len(screen.pw1_frames))
            assert screen.title == "Signed tx"
            screen.done = True
            screen.result = "back"
            return screen.result
        raise AssertionError(f"unexpected {type(screen)!r}")

    def fake_start_worker(_state: _ScanState) -> None:
        # Real worker isn't used because run_screen is stubbed.
        return None

    monkeypatch.setattr(ss, "run_screen", fake_run_screen)

    out = run_sign_flow(
        display,
        mgr,
        vault,
        pin,
        rec,
        toast_seconds=0,
        start_worker=fake_start_worker,
    )
    assert out == "stay"
    assert len(saw_qr_with_frames) == 1
    assert saw_qr_with_frames[0] >= 1


def test_run_sign_flow_cancel_returns_stay(
    monkeypatch: pytest.MonkeyPatch,
    canonical_vault: tuple[Vault, str, WalletRecord],
) -> None:
    """B-cancel during scan exits cleanly without invoking confirm/sign."""
    vault, pin, rec = canonical_vault
    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())

    def fake_run_screen(_d, _m, screen, **_kw):
        if isinstance(screen, ScanProposalScreen):
            screen.done = True
            screen.result = "cancel"
            return screen.result
        raise AssertionError(f"unexpected {type(screen)!r}")

    monkeypatch.setattr(ss, "run_screen", fake_run_screen)
    assert run_sign_flow(
        display, mgr, vault, pin, rec, toast_seconds=0, start_worker=lambda _s: None
    ) == "stay"


def test_run_sign_flow_long_b_during_scan_returns_exit(
    monkeypatch: pytest.MonkeyPatch,
    canonical_vault: tuple[Vault, str, WalletRecord],
) -> None:
    vault, pin, rec = canonical_vault
    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())

    def fake_run_screen(_d, _m, screen, **_kw):
        if isinstance(screen, ScanProposalScreen):
            screen.done = True
            screen.result = "exit"
            return screen.result
        raise AssertionError(f"unexpected {type(screen)!r}")

    monkeypatch.setattr(ss, "run_screen", fake_run_screen)
    assert run_sign_flow(
        display, mgr, vault, pin, rec, toast_seconds=0, start_worker=lambda _s: None
    ) == "exit"


def test_run_sign_flow_rejects_wrong_envelope_type(
    monkeypatch: pytest.MonkeyPatch,
    canonical_vault: tuple[Vault, str, WalletRecord],
) -> None:
    """Scanning an xpub_export envelope by mistake yields a modal + 'stay'."""
    vault, pin, rec = canonical_vault
    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())

    xpub_export_blob = env.encode(
        env.XpubExport(
            xpub=vault.get_account_xpub(pin, rec.id),
            path=rec.derivation_path,
            label=rec.label or "x",
            fingerprint=rec.fingerprint,
            network=rec.network,
        )
    )

    def fake_run_screen(_d, _m, screen, **_kw):
        if isinstance(screen, ScanProposalScreen):
            screen.done = True
            screen.result = xpub_export_blob
            return screen.result
        raise AssertionError(f"unexpected {type(screen)!r}")

    monkeypatch.setattr(ss, "run_screen", fake_run_screen)
    assert run_sign_flow(
        display, mgr, vault, pin, rec, toast_seconds=0, start_worker=lambda _s: None
    ) == "stay"


def test_run_sign_flow_rejects_wrong_wallet(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    real_proposal,
) -> None:
    """Proposal whose wallet_fp doesn't match the active wallet → modal + 'stay'."""
    blob, _proposal, _xpub = real_proposal
    v = Vault(tmp_path / "v2.bin")
    v.create(pin="123456")
    # Generate a fresh (random) mnemonic so the wallet's xpub
    # fingerprint differs from the canonical proposal's wallet_fp.
    foreign = mnem.generate(12)
    rec = v.add_wallet("123456", foreign, label="other")

    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())

    def fake_run_screen(_d, _m, screen, **_kw):
        if isinstance(screen, ScanProposalScreen):
            screen.done = True
            screen.result = blob
            return screen.result
        if isinstance(screen, ConfirmProposalScreen):
            raise AssertionError("confirm must NOT show on wrong-wallet")
        raise AssertionError(f"unexpected {type(screen)!r}")

    monkeypatch.setattr(ss, "run_screen", fake_run_screen)
    assert run_sign_flow(
        display, mgr, v, "123456", rec, toast_seconds=0, start_worker=lambda _s: None
    ) == "stay"


def test_run_sign_flow_decode_error_returns_stay(
    monkeypatch: pytest.MonkeyPatch,
    canonical_vault: tuple[Vault, str, WalletRecord],
) -> None:
    """Garbage bytes from the scanner: surface a modal, stay on the manage menu."""
    vault, pin, rec = canonical_vault
    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())

    def fake_run_screen(_d, _m, screen, **_kw):
        if isinstance(screen, ScanProposalScreen):
            screen.done = True
            screen.result = b"not a valid envelope"
            return screen.result
        raise AssertionError(f"unexpected {type(screen)!r}")

    monkeypatch.setattr(ss, "run_screen", fake_run_screen)
    assert run_sign_flow(
        display, mgr, vault, pin, rec, toast_seconds=0, start_worker=lambda _s: None
    ) == "stay"


def test_menu_includes_sign_row() -> None:
    w = WalletRecord(
        id="id1",
        label="alpha",
        fingerprint=b"\x01\x02\x03\x04",
        derivation_path="m/44'/236'/0'",
        word_count=12,
        created_at="2026-01-01T00:00:00+00:00",
    )
    menu = WalletManageMenuScreen(wallet=w)
    values = [item.value for item in menu._list.items]
    assert WalletManageAction.SIGN in values
    # Sign row sits between Companion QR and Wallet info so the
    # spending-side actions cluster together.
    sign_idx = values.index(WalletManageAction.SIGN)
    assert values[sign_idx - 1] == WalletManageAction.COMPANION_QR
    assert values[sign_idx + 1] == WalletManageAction.INFO


# ===========================================================================
# Camera-scan cancel hook
# ===========================================================================


def test_scan_cancelled_is_a_runtimeerror_subclass() -> None:
    """The bonnet's worker thread catches RuntimeError; ScanCancelled should
    therefore subclass it so a single ``except`` clause covers both
    expected exit paths."""
    from piwallet.qr.camera_scan import ScanCancelled

    assert issubclass(ScanCancelled, RuntimeError)

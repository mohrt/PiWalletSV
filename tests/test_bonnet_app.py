"""Integration test: drive run_bonnet() through a real Vault + headless UI."""

from __future__ import annotations

from pathlib import Path

import pytest

from piwallet.bonnet.app import run_bonnet
from piwallet.core import mnemonic as mnem
from piwallet.core.vault import Vault
from piwallet.ui.display import HeadlessDisplay
from piwallet.ui.input import Button, FakeInputBackend, InputManager


@pytest.fixture()
def fresh_vault(tmp_path: Path) -> tuple[Path, str]:
    """A vault containing one wallet under PIN 123456."""
    vault_path = tmp_path / "vault.bin"
    v = Vault(vault_path)
    v.create(pin="123456")
    v.add_wallet(
        pin="123456",
        mnemonic_phrase=mnem.generate(12),
        label="daily",
    )
    return vault_path, "123456"


@pytest.fixture()
def accepted_terms(tmp_path: Path) -> Path:
    """A terms.json file marking the current disclaimer as already accepted."""
    from piwallet.firstboot.terms import mark_accepted
    state_file = tmp_path / "terms.json"
    mark_accepted(state_file, now=lambda: "2026-05-10T15:20:30+00:00")
    return state_file


def _drive(
    backend: FakeInputBackend,
    mgr: InputManager,
    display: HeadlessDisplay,
    actions: list[tuple[Button, bool]],
) -> None:
    """Helper: leave button states pre-set so each run_screen loop sees them.

    Each action is ``(button, pressed)``. ``run_bonnet`` runs in a
    separate thread (set up by the caller); this helper just sets
    backend state.
    """
    for button, pressed in actions:
        backend.set(button, pressed)


def test_no_vault_returns_exit_code_1(tmp_path: Path, accepted_terms: Path) -> None:
    """If the vault doesn't exist, run_bonnet exits 1 and shows a banner."""
    backend = FakeInputBackend()
    mgr = InputManager(backend)
    display = HeadlessDisplay()
    code = run_bonnet(
        vault_path=tmp_path / "missing-vault.bin",
        display=display,
        input_mgr=mgr,
        terms_path=accepted_terms,
        target_fps=1000,
    )
    assert code == 1
    # The "No vault" banner should have rendered at least once.
    assert display.flip_count >= 1


def test_disclaimer_declined_returns_exit_code_2(tmp_path: Path) -> None:
    """If the disclaimer is bailed (long-B), run_bonnet exits 2."""
    backend = FakeInputBackend()

    class _Clock:
        def __init__(self) -> None:
            self.now = 0

        def __call__(self) -> int:
            self.now += 50
            return self.now

    clock = _Clock()
    mgr = InputManager(backend, clock=clock)
    display = HeadlessDisplay()

    # Press and HOLD B from the start; the disclaimer's long-press LONG
    # handler fires at long_ms=700 (default) and bails.
    backend.press(Button.B)

    code = run_bonnet(
        vault_path=tmp_path / "vault.bin",
        display=display,
        input_mgr=mgr,
        terms_path=tmp_path / "terms.json",
        target_fps=1000,
    )
    assert code == 2


def test_verify_fn_routes_vault_errors(fresh_vault: tuple[Path, str]) -> None:
    """The PIN-verify closure produced by _make_verify_fn maps vault
    exceptions to the wire ('ok' | 'wrong' | 'wiped') protocol expected
    by UnlockScreen.
    """
    from piwallet.bonnet.app import _make_verify_fn

    vault_path, good_pin = fresh_vault
    vault = Vault(vault_path)
    verify = _make_verify_fn(vault)

    outcome, info = verify(good_pin)
    assert outcome == "ok"
    assert info is None

    outcome, info = verify("999999")
    assert outcome == "wrong"
    assert isinstance(info, int) and info > 0


def test_derive_address_fn_returns_p2pkh_for_indices(
    fresh_vault: tuple[Path, str],
) -> None:
    """The address-deriver closure produces real BSV mainnet P2PKH
    addresses for distinct (change, index) pairs - exercising the
    full path the bonnet uses for the receive screen.
    """
    from piwallet.bonnet.app import _make_derive_address_fn

    vault_path, pin = fresh_vault
    vault = Vault(vault_path)
    wallet_id = vault.list_wallets()[0].id
    derive = _make_derive_address_fn(vault, wallet_id, pin)

    addr_0_0 = derive(0, 0)
    addr_0_1 = derive(0, 1)
    addr_1_0 = derive(1, 0)
    for addr in (addr_0_0, addr_0_1, addr_1_0):
        assert isinstance(addr, str)
        assert 26 <= len(addr) <= 35  # Base58Check P2PKH range
    assert addr_0_0 != addr_0_1
    assert addr_0_0 != addr_1_0

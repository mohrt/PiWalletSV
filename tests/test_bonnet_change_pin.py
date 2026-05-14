"""Tests for the bonnet change-PIN flow."""

from __future__ import annotations

from pathlib import Path

import pytest

from piwallet.bonnet import change_pin as cp
from piwallet.bonnet.unlock import UnlockOutcome, UnlockScreen
from piwallet.core import mnemonic as mnem
from piwallet.core.vault import Vault, WalletRecord, WrongPinError
from piwallet.ui.display import HeadlessDisplay
from piwallet.ui.input import FakeInputBackend, InputManager
from piwallet.ui.pin_setup import PinSetupScreen


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cp.time, "sleep", lambda _: None)


@pytest.fixture(autouse=True)
def _fast_scrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    from piwallet.core import vault as vlt

    monkeypatch.setattr(vlt, "SCRYPT_N", 2**12)


@pytest.fixture()
def vault_with_wallet(tmp_path: Path) -> tuple[Vault, str, WalletRecord]:
    path = tmp_path / "vault.bin"
    v = Vault(path)
    v.create(pin="123456")
    rec = v.add_wallet("123456", mnem.generate(12), label="alpha")
    return v, "123456", rec


@pytest.fixture()
def empty_vault(tmp_path: Path) -> Vault:
    path = tmp_path / "vault.bin"
    v = Vault(path)
    v.create(pin="123456")
    return v


def _make_runner(
    monkeypatch: pytest.MonkeyPatch,
    *,
    unlock_outcome: UnlockOutcome | None,
    setup_pin: str | None,
    forbidden: tuple[type, ...] = (),
) -> list[object]:
    """Stub ``change_pin.run_screen`` to feed deterministic results.

    ``forbidden`` lets a test assert a particular screen class must
    NOT be instantiated (e.g. PinSetupScreen on the wiped path).
    """
    captured: list[object] = []

    def fake_run_screen(display, mgr, screen, **_):
        captured.append(screen)
        if isinstance(screen, UnlockScreen):
            if isinstance(screen, forbidden):
                raise AssertionError(
                    "unexpected UnlockScreen run after stop signal"
                )
            screen.done = True
            screen.result = unlock_outcome
            return unlock_outcome
        if isinstance(screen, PinSetupScreen):
            if isinstance(screen, forbidden):
                raise AssertionError(
                    "unexpected PinSetupScreen run after stop signal"
                )
            screen.done = True
            screen.result = setup_pin
            return setup_pin
        raise AssertionError(f"unexpected screen {type(screen)}")

    monkeypatch.setattr(cp, "run_screen", fake_run_screen)
    return captured


def test_change_pin_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    vault_with_wallet: tuple[Vault, str, WalletRecord],
) -> None:
    vault, pin, rec = vault_with_wallet
    _make_runner(
        monkeypatch,
        unlock_outcome=UnlockOutcome(kind="ok", pin=pin),
        setup_pin="999999",
    )
    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())

    result, new_pin = cp.run_change_pin(display, mgr, vault, pin, toast_seconds=0)

    assert result == "changed"
    assert new_pin == "999999"
    # The new PIN unlocks the wallet; the old one no longer does.
    assert vault.get_account_xpub("999999", rec.id).startswith("xpub")
    with pytest.raises(WrongPinError):
        vault.get_account_xpub(pin, rec.id)


def test_change_pin_wiped_during_verify(
    monkeypatch: pytest.MonkeyPatch,
    vault_with_wallet: tuple[Vault, str, WalletRecord],
) -> None:
    """If the verify step trips the lockout, propagate as ``"wiped"``
    and never reach the PinSetupScreen."""
    vault, pin, _ = vault_with_wallet
    _make_runner(
        monkeypatch,
        unlock_outcome=UnlockOutcome(kind="wiped", pin=None),
        setup_pin=None,
        forbidden=(PinSetupScreen,),
    )
    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())

    result, new_pin = cp.run_change_pin(display, mgr, vault, pin, toast_seconds=0)

    assert result == "wiped"
    assert new_pin is None


def test_change_pin_cancelled_at_pin_setup(
    monkeypatch: pytest.MonkeyPatch,
    vault_with_wallet: tuple[Vault, str, WalletRecord],
) -> None:
    """Long-B inside the new-PIN screen returns ``setup.result is None``.
    The flow must report ``"cancelled"`` and leave the vault PIN
    unchanged."""
    vault, pin, rec = vault_with_wallet
    _make_runner(
        monkeypatch,
        unlock_outcome=UnlockOutcome(kind="ok", pin=pin),
        setup_pin=None,
    )
    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())

    result, new_pin = cp.run_change_pin(display, mgr, vault, pin, toast_seconds=0)

    assert result == "cancelled"
    assert new_pin is None
    # Vault still uses the original PIN.
    assert vault.get_account_xpub(pin, rec.id).startswith("xpub")


def test_change_pin_cancels_when_new_equals_current(
    monkeypatch: pytest.MonkeyPatch,
    vault_with_wallet: tuple[Vault, str, WalletRecord],
) -> None:
    """Selecting the same PIN twice is treated as a no-op cancel —
    we don't pretend to "change" anything and we don't waste a salt
    rotation. The user sees a "No change" toast."""
    vault, pin, rec = vault_with_wallet
    _make_runner(
        monkeypatch,
        unlock_outcome=UnlockOutcome(kind="ok", pin=pin),
        setup_pin=pin,
    )
    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())

    result, new_pin = cp.run_change_pin(display, mgr, vault, pin, toast_seconds=0)
    assert result == "cancelled"
    assert new_pin is None
    # Vault still uses the original PIN.
    assert vault.get_account_xpub(pin, rec.id).startswith("xpub")


def test_change_pin_on_empty_vault_succeeds(
    monkeypatch: pytest.MonkeyPatch, empty_vault: Vault
) -> None:
    """Empty vault has no ciphertext — verify accepts any well-formed
    PIN, change_pin rotates the salt, the flow reports ``"changed"``."""
    pin = "123456"
    _make_runner(
        monkeypatch,
        unlock_outcome=UnlockOutcome(kind="ok", pin=pin),
        setup_pin="999999",
    )
    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())

    result, new_pin = cp.run_change_pin(display, mgr, empty_vault, pin, toast_seconds=0)
    assert result == "changed"
    assert new_pin == "999999"


def test_change_pin_unlock_screen_titled_current_pin(
    monkeypatch: pytest.MonkeyPatch,
    vault_with_wallet: tuple[Vault, str, WalletRecord],
) -> None:
    """The first UnlockScreen rendered by the change-PIN flow must
    title itself "Current PIN" so the operator isn't confused with
    the boot-time unlock prompt."""
    vault, pin, _ = vault_with_wallet
    captured = _make_runner(
        monkeypatch,
        unlock_outcome=UnlockOutcome(kind="ok", pin=pin),
        setup_pin="999999",
    )
    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())

    cp.run_change_pin(display, mgr, vault, pin, toast_seconds=0)

    unlocks = [s for s in captured if isinstance(s, UnlockScreen)]
    assert unlocks, "expected at least one UnlockScreen"
    assert unlocks[0].pin_entry.title == "Current PIN"


def test_change_pin_pin_setup_is_cancellable(
    monkeypatch: pytest.MonkeyPatch,
    vault_with_wallet: tuple[Vault, str, WalletRecord],
) -> None:
    """The new-PIN screen must accept long-B as cancel; otherwise
    the operator would have no way out after typing the current
    PIN."""
    vault, pin, _ = vault_with_wallet
    captured = _make_runner(
        monkeypatch,
        unlock_outcome=UnlockOutcome(kind="ok", pin=pin),
        setup_pin="999999",
    )
    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())

    cp.run_change_pin(display, mgr, vault, pin, toast_seconds=0)

    setups = [s for s in captured if isinstance(s, PinSetupScreen)]
    assert setups, "expected at least one PinSetupScreen"
    assert all(s.cancellable for s in setups)


def test_verify_fn_for_empty_vault_accepts_any_well_formed_pin(
    empty_vault: Vault,
) -> None:
    verify = cp._make_verify_fn(empty_vault)
    assert verify("123456") == ("ok", None)


def test_verify_fn_for_populated_vault_returns_wrong_for_bad_pin(
    vault_with_wallet: tuple[Vault, str, WalletRecord],
) -> None:
    vault, _pin, _rec = vault_with_wallet
    verify = cp._make_verify_fn(vault)
    outcome, remaining = verify("999999")
    assert outcome == "wrong"
    assert isinstance(remaining, int)
    assert remaining < vault._state.pin_attempt_threshold  # type: ignore[union-attr]

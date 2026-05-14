"""Tests for the first-boot vault setup flow."""

from __future__ import annotations

from pathlib import Path

import pytest

from piwallet.bonnet import vault_setup as vs
from piwallet.core.vault import Vault, VaultError
from piwallet.ui.display import HeadlessDisplay
from piwallet.ui.input import FakeInputBackend, InputManager
from piwallet.ui.pin_setup import PinSetupScreen


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the modal hold-time sleeps so tests run instantly."""
    monkeypatch.setattr(vs.time, "sleep", lambda _: None)


@pytest.fixture(autouse=True)
def _fast_scrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reduce scrypt cost for vault.create()."""
    from piwallet.core import vault as vlt

    monkeypatch.setattr(vlt, "SCRYPT_N", 2**12)


def _stub_pin_setup(
    monkeypatch: pytest.MonkeyPatch, *, pin_sequence: list[str | None]
) -> list[PinSetupScreen]:
    """Replace ``vault_setup.run_screen`` with a stub that fills in the
    PinSetupScreen instance's result from ``pin_sequence`` in order.

    Returns the captured screen instances so tests can assert on
    construction args (e.g. ``cancellable=False``).
    """
    captured: list[PinSetupScreen] = []
    seq = list(pin_sequence)

    def fake_run_screen(display, mgr, screen, **_):
        assert isinstance(screen, PinSetupScreen)
        captured.append(screen)
        result = seq.pop(0)
        screen.done = True
        screen.result = result
        return result

    monkeypatch.setattr(vs, "run_screen", fake_run_screen)
    return captured


def test_run_vault_setup_creates_vault_and_returns_pin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured = _stub_pin_setup(monkeypatch, pin_sequence=["112233"])

    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())
    vault_path = tmp_path / "vault.bin"

    result = vs.run_vault_setup(
        display,
        mgr,
        vault_path,
        welcome_hold_seconds=0,
        saved_hold_seconds=0,
    )

    assert result is not None
    vault, pin = result
    assert pin == "112233"
    assert vault.exists is True
    assert vault.is_initialized is True
    # The PinSetupScreen we used must have been non-cancellable.
    assert captured[0].cancellable is False
    # And titled to make the first-boot intent obvious.
    assert captured[0].prompt == "Choose vault PIN"


def test_run_vault_setup_retries_when_pin_setup_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If the first run_screen call somehow returns without a PIN
    (e.g. an idle blank cycle ate the screen), the loop reissues a
    fresh PinSetupScreen rather than crashing the bonnet."""
    _stub_pin_setup(monkeypatch, pin_sequence=[None, "112233"])

    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())
    vault_path = tmp_path / "vault.bin"

    result = vs.run_vault_setup(
        display,
        mgr,
        vault_path,
        welcome_hold_seconds=0,
        saved_hold_seconds=0,
    )

    assert result is not None
    _, pin = result
    assert pin == "112233"


def test_run_vault_setup_returns_none_when_create_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A pre-existing vault file at the path makes ``vault.create``
    raise; the flow surfaces that as ``None`` so the caller can fall
    back to the legacy "use the CLI" exit code."""
    _stub_pin_setup(monkeypatch, pin_sequence=["112233"])

    vault_path = tmp_path / "vault.bin"
    # Plant a non-empty file so Vault.create refuses to overwrite.
    vault_path.write_bytes(b"placeholder")

    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())

    result = vs.run_vault_setup(
        display,
        mgr,
        vault_path,
        welcome_hold_seconds=0,
        saved_hold_seconds=0,
    )

    assert result is None


def test_run_vault_setup_is_uninterruptible_on_a_partial_pin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``cancellable=False`` is the contract for first boot — verify
    that the PinSetupScreen objects the runner constructs honour it.
    Indirect coverage: the flow's user-visible behaviour (returning
    a PIN) is already tested above; here we just spot-check the
    construction kwargs so a future refactor can't silently flip the
    flag and quietly let an operator skip vault setup."""
    captured = _stub_pin_setup(monkeypatch, pin_sequence=[None, "112233"])

    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())
    vault_path = tmp_path / "vault.bin"

    vs.run_vault_setup(
        display,
        mgr,
        vault_path,
        welcome_hold_seconds=0,
        saved_hold_seconds=0,
    )

    # All retries must also be non-cancellable.
    assert all(s.cancellable is False for s in captured)


def test_run_vault_setup_persists_to_disk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Re-opening the vault from disk after setup proves it was saved."""
    _stub_pin_setup(monkeypatch, pin_sequence=["112233"])

    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())
    vault_path = tmp_path / "vault.bin"

    result = vs.run_vault_setup(
        display,
        mgr,
        vault_path,
        welcome_hold_seconds=0,
        saved_hold_seconds=0,
    )
    assert result is not None

    fresh = Vault(vault_path)
    assert fresh.exists is True
    assert fresh.is_initialized is True
    assert fresh.list_wallets() == []


def test_run_vault_setup_surfaces_create_validation_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If something forces ``vault.create`` to raise a non-existence
    VaultError, we should still return ``None`` so the caller exits
    cleanly. Easiest way to provoke this is via monkey-patching."""
    _stub_pin_setup(monkeypatch, pin_sequence=["112233"])

    def boom(self, pin):
        raise VaultError("synthetic")

    monkeypatch.setattr(Vault, "create", boom)

    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())
    result = vs.run_vault_setup(
        display,
        mgr,
        tmp_path / "vault.bin",
        welcome_hold_seconds=0,
        saved_hold_seconds=0,
    )
    assert result is None

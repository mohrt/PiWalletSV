"""wallet_manage orchestration."""

from __future__ import annotations

from pathlib import Path

import pytest

from piwallet.bonnet import wallet_manage as wm
from piwallet.bonnet.wallet_detail import WalletDetailScreen
from piwallet.bonnet.wallet_manage import (
    WalletManageAction,
    WalletManageMenuScreen,
)
from piwallet.core import mnemonic as mnem
from piwallet.core.vault import Vault, WalletRecord
from piwallet.ui.display import FrameBuffer, HeadlessDisplay
from piwallet.ui.double_confirm import DoubleConfirmScreen
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.label_entry import WalletLabelEntryScreen
from piwallet.ui.pairing_multipart_qr_screen import PairingMultipartQrScreen


def _press(b: Button) -> Event:
    return Event(button=b, kind=EventKind.PRESS, at_ms=0)


@pytest.fixture()
def vault_and_wallet(tmp_path: Path) -> tuple[Vault, str, WalletRecord]:
    path = tmp_path / "v.bin"
    v = Vault(path)
    v.create(pin="123456")
    rec = v.add_wallet("123456", mnem.generate(12), label="alpha")
    return v, "123456", rec


def test_menu_long_b_is_back() -> None:
    w = WalletRecord(
        id="id1",
        label="w",
        fingerprint=b"\x01\x02\x03\x04",
        derivation_path="m/44'/236'/0'",
        word_count=12,
        created_at="2026-01-01T00:00:00+00:00",
    )
    m = WalletManageMenuScreen(wallet=w)
    m.on_event(Event(button=Button.B, kind=EventKind.LONG, at_ms=0))
    assert m.done and m.result is WalletManageAction.BACK


def test_menu_short_b_is_also_back() -> None:
    """Short tap of B from the manage menu drops back to the wallet list.

    Operators should not have to hold B; the menu has an explicit ``< Back``
    row, so a brief press of B is the natural shortcut.
    """
    w = WalletRecord(
        id="id1",
        label="w",
        fingerprint=b"\x01\x02\x03\x04",
        derivation_path="m/44'/236'/0'",
        word_count=12,
        created_at="2026-01-01T00:00:00+00:00",
    )
    m = WalletManageMenuScreen(wallet=w)
    m.on_event(Event(button=Button.B, kind=EventKind.PRESS, at_ms=0))
    assert m.done and m.result is WalletManageAction.BACK


def test_menu_draw_smoke() -> None:
    w = WalletRecord(
        id="id1",
        label="w",
        fingerprint=b"\x01\x02\x03\x04",
        derivation_path="m/44'/236'/0'",
        word_count=12,
        created_at="2026-01-01T00:00:00+00:00",
    )
    fb = FrameBuffer()
    WalletManageMenuScreen(wallet=w).draw(fb)


def test_run_rename_with_stubbed_screens(
    monkeypatch: pytest.MonkeyPatch,
    vault_and_wallet: tuple[Vault, str, WalletRecord],
) -> None:
    """Rename: only the label editor confirms; no separate double-confirm."""
    vault, pin, rec = vault_and_wallet
    display = HeadlessDisplay()
    from piwallet.ui.input import FakeInputBackend, InputManager

    mgr = InputManager(FakeInputBackend())

    def fake_run_screen(display, mgr, screen, **_):
        if isinstance(screen, WalletManageMenuScreen):
            screen.done = True
            screen.result = WalletManageAction.RENAME
            return screen.result
        if isinstance(screen, WalletLabelEntryScreen):
            # The label editor itself runs the user through Save / Edit /
            # Cancel; the runner only sees the final ``.result``.
            screen.done = True
            screen.result = "omega"
            return screen.result
        if isinstance(screen, DoubleConfirmScreen):
            raise AssertionError("rename must NOT show a double-confirm screen")
        raise AssertionError(f"unexpected {type(screen)}")

    monkeypatch.setattr(wm, "run_screen", fake_run_screen)
    monkeypatch.setattr(wm.time, "sleep", lambda _: None)

    out = wm.run_wallet_manage(display, mgr, vault, pin, rec, toast_seconds=0)
    assert out == "renamed"
    wallets = vault.list_wallets()
    assert len(wallets) == 1
    assert wallets[0].label == "omega"


def test_run_erase_with_stubbed_screens(
    monkeypatch: pytest.MonkeyPatch,
    vault_and_wallet: tuple[Vault, str, WalletRecord],
) -> None:
    vault, pin, rec = vault_and_wallet
    display = HeadlessDisplay()
    from piwallet.ui.input import FakeInputBackend, InputManager

    mgr = InputManager(FakeInputBackend())

    def fake_run_screen(display, mgr, screen, **_):
        if isinstance(screen, WalletManageMenuScreen):
            screen.done = True
            screen.result = WalletManageAction.DELETE
            return screen.result
        if isinstance(screen, DoubleConfirmScreen):
            screen.on_event(_press(Button.A))
            screen.on_event(_press(Button.A))
            return screen.result
        raise AssertionError(f"unexpected {type(screen)!r}")

    monkeypatch.setattr(wm, "run_screen", fake_run_screen)
    monkeypatch.setattr(wm.time, "sleep", lambda _: None)

    out = wm.run_wallet_manage(display, mgr, vault, pin, rec, toast_seconds=0)
    assert out == "deleted"
    assert vault.list_wallets() == []


def test_run_returns_back_on_menu_back(
    monkeypatch: pytest.MonkeyPatch,
    vault_and_wallet: tuple[Vault, str, WalletRecord],
) -> None:
    vault, pin, rec = vault_and_wallet
    display = HeadlessDisplay()
    from piwallet.ui.input import FakeInputBackend, InputManager

    mgr = InputManager(FakeInputBackend())

    def fake_run_screen(display, mgr, screen, **_):
        assert isinstance(screen, WalletManageMenuScreen)
        screen.done = True
        screen.result = WalletManageAction.BACK
        return screen.result

    monkeypatch.setattr(wm, "run_screen", fake_run_screen)

    assert wm.run_wallet_manage(display, mgr, vault, pin, rec, toast_seconds=0) == "back"


def test_run_receive_runs_detail_then_stays(
    monkeypatch: pytest.MonkeyPatch,
    vault_and_wallet: tuple[Vault, str, WalletRecord],
) -> None:
    """Selecting Receive runs WalletDetailScreen; B-back returns to menu (\"stay\")."""
    vault, pin, rec = vault_and_wallet
    display = HeadlessDisplay()
    from piwallet.ui.input import FakeInputBackend, InputManager

    mgr = InputManager(FakeInputBackend())

    seen: list[str] = []

    def fake_run_screen(display, mgr, screen, **_):
        if isinstance(screen, WalletManageMenuScreen):
            seen.append("menu")
            screen.done = True
            screen.result = WalletManageAction.RECEIVE
            return screen.result
        if isinstance(screen, WalletDetailScreen):
            seen.append("detail")
            screen.done = True
            screen.result = "back"
            return screen.result
        raise AssertionError(f"unexpected {type(screen)!r}")

    monkeypatch.setattr(wm, "run_screen", fake_run_screen)

    assert wm.run_wallet_manage(display, mgr, vault, pin, rec, toast_seconds=0) == "stay"
    assert seen == ["menu", "detail"]


def test_run_receive_exit_propagates(
    monkeypatch: pytest.MonkeyPatch,
    vault_and_wallet: tuple[Vault, str, WalletRecord],
) -> None:
    """Long-B inside the detail screen propagates as \"exit\"."""
    vault, pin, rec = vault_and_wallet
    display = HeadlessDisplay()
    from piwallet.ui.input import FakeInputBackend, InputManager

    mgr = InputManager(FakeInputBackend())

    def fake_run_screen(display, mgr, screen, **_):
        if isinstance(screen, WalletManageMenuScreen):
            screen.done = True
            screen.result = WalletManageAction.RECEIVE
            return screen.result
        if isinstance(screen, WalletDetailScreen):
            screen.done = True
            screen.result = "exit"
            return screen.result
        raise AssertionError(f"unexpected {type(screen)!r}")

    monkeypatch.setattr(wm, "run_screen", fake_run_screen)

    assert wm.run_wallet_manage(display, mgr, vault, pin, rec, toast_seconds=0) == "exit"


def test_menu_lists_every_action_in_order() -> None:
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
    assert values == [
        WalletManageAction.RECEIVE,
        WalletManageAction.COMPANION_QR,
        WalletManageAction.INFO,
        WalletManageAction.RENAME,
        WalletManageAction.DELETE,
        WalletManageAction.BACK,
    ]


def test_run_info_runs_info_screen_then_stays(
    monkeypatch: pytest.MonkeyPatch,
    vault_and_wallet: tuple[Vault, str, WalletRecord],
) -> None:
    """Selecting Wallet info opens WalletInfoScreen; B-back returns to menu."""
    from piwallet.bonnet.wallet_info import WalletInfoScreen

    vault, pin, rec = vault_and_wallet
    display = HeadlessDisplay()
    from piwallet.ui.input import FakeInputBackend, InputManager

    mgr = InputManager(FakeInputBackend())
    seen: list[str] = []

    def fake_run_screen(display, mgr, screen, **_):
        if isinstance(screen, WalletManageMenuScreen):
            seen.append("menu")
            screen.done = True
            screen.result = WalletManageAction.INFO
            return screen.result
        if isinstance(screen, WalletInfoScreen):
            seen.append("info")
            assert screen.wallet.derivation_path == rec.derivation_path
            screen.done = True
            screen.result = "back"
            return screen.result
        raise AssertionError(f"unexpected {type(screen)!r}")

    monkeypatch.setattr(wm, "run_screen", fake_run_screen)

    assert wm.run_wallet_manage(display, mgr, vault, pin, rec, toast_seconds=0) == "stay"
    assert seen == ["menu", "info"]


def test_run_info_exit_propagates(
    monkeypatch: pytest.MonkeyPatch,
    vault_and_wallet: tuple[Vault, str, WalletRecord],
) -> None:
    """Long-B inside the info screen propagates as ``exit``."""
    from piwallet.bonnet.wallet_info import WalletInfoScreen

    vault, pin, rec = vault_and_wallet
    display = HeadlessDisplay()
    from piwallet.ui.input import FakeInputBackend, InputManager

    mgr = InputManager(FakeInputBackend())

    def fake_run_screen(display, mgr, screen, **_):
        if isinstance(screen, WalletManageMenuScreen):
            screen.done = True
            screen.result = WalletManageAction.INFO
            return screen.result
        if isinstance(screen, WalletInfoScreen):
            screen.done = True
            screen.result = "exit"
            return screen.result
        raise AssertionError(f"unexpected {type(screen)!r}")

    monkeypatch.setattr(wm, "run_screen", fake_run_screen)

    assert wm.run_wallet_manage(display, mgr, vault, pin, rec, toast_seconds=0) == "exit"


def test_run_companion_qr_back_returns_stay(
    monkeypatch: pytest.MonkeyPatch,
    vault_and_wallet: tuple[Vault, str, WalletRecord],
) -> None:
    vault, pin, rec = vault_and_wallet
    display = HeadlessDisplay()
    from piwallet.ui.input import FakeInputBackend, InputManager

    mgr = InputManager(FakeInputBackend())
    lines = ["PW1|1|0|eA"]

    monkeypatch.setattr(wm, "pairing_pw1_lines", lambda *_a, **_k: lines)

    def fake_run_screen(display, mgr, screen, **_):
        if isinstance(screen, WalletManageMenuScreen):
            screen.done = True
            screen.result = WalletManageAction.COMPANION_QR
            return screen.result
        if isinstance(screen, PairingMultipartQrScreen):
            assert screen.pw1_frames == lines
            screen.done = True
            screen.result = "back"
            return screen.result
        raise AssertionError(f"unexpected {type(screen)!r}")

    monkeypatch.setattr(wm, "run_screen", fake_run_screen)
    monkeypatch.setattr(wm.time, "sleep", lambda _: None)

    assert wm.run_wallet_manage(display, mgr, vault, pin, rec, toast_seconds=0) == "stay"


def test_run_companion_qr_exit_propagates(
    monkeypatch: pytest.MonkeyPatch,
    vault_and_wallet: tuple[Vault, str, WalletRecord],
) -> None:
    vault, pin, rec = vault_and_wallet
    display = HeadlessDisplay()
    from piwallet.ui.input import FakeInputBackend, InputManager

    mgr = InputManager(FakeInputBackend())
    lines = ["PW1|1|0|eA"]

    monkeypatch.setattr(wm, "pairing_pw1_lines", lambda *_a, **_k: lines)

    def fake_run_screen(display, mgr, screen, **_):
        if isinstance(screen, WalletManageMenuScreen):
            screen.done = True
            screen.result = WalletManageAction.COMPANION_QR
            return screen.result
        if isinstance(screen, PairingMultipartQrScreen):
            screen.done = True
            screen.result = "exit"
            return screen.result
        raise AssertionError(f"unexpected {type(screen)!r}")

    monkeypatch.setattr(wm, "run_screen", fake_run_screen)
    monkeypatch.setattr(wm.time, "sleep", lambda _: None)

    assert wm.run_wallet_manage(display, mgr, vault, pin, rec, toast_seconds=0) == "exit"

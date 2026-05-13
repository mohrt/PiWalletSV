"""WalletListScreen tests."""

from __future__ import annotations

from piwallet.bonnet.wallet_list import WalletListAction, WalletListScreen
from piwallet.core.vault import WalletRecord
from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind


def _evt(b: Button, k: EventKind = EventKind.PRESS, at_ms: int = 0) -> Event:
    return Event(button=b, kind=k, at_ms=at_ms)


def _wallet(label: str, idx: int = 0) -> WalletRecord:
    return WalletRecord(
        id=f"wallet-{idx}",
        label=label,
        fingerprint=bytes([idx, idx + 1, idx + 2, idx + 3]),
        derivation_path="m/44'/236'/0'",
        word_count=12,
        created_at="2026-05-10T00:00:00+00:00",
    )


def test_list_navigates_and_confirms() -> None:
    wallets = [_wallet("daily", 0), _wallet("savings", 1), _wallet("cold", 2)]
    s = WalletListScreen(wallets=wallets)
    assert s.cursor == 0
    s.on_event(_evt(Button.DOWN))
    assert s.cursor == 1
    s.on_event(_evt(Button.A))
    assert s.done is True
    assert s.result == "wallet-1"


def test_list_long_b_exits_with_none() -> None:
    wallets = [_wallet("daily")]
    s = WalletListScreen(wallets=wallets)
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.done is True
    assert s.result is None


def test_list_empty_still_offers_actions() -> None:
    s = WalletListScreen(wallets=[])
    # First row is now "+ New wallet"; A confirms it.
    s.on_event(_evt(Button.A))
    assert s.done is True
    assert s.result is WalletListAction.NEW


def test_list_offers_new_and_restore_at_bottom() -> None:
    wallets = [_wallet("daily", 0), _wallet("savings", 1)]
    s = WalletListScreen(wallets=wallets)
    # 2 wallets + 3 actions (new/restore/settings) = 5 rows.
    # Cursor 0 -> 1 -> 2 lands on "+ New wallet".
    s.on_event(_evt(Button.DOWN))
    s.on_event(_evt(Button.DOWN))
    assert s.cursor == 2
    s.on_event(_evt(Button.A))
    assert s.done is True
    assert s.result is WalletListAction.NEW


def test_list_restore_action() -> None:
    wallets = [_wallet("daily")]
    s = WalletListScreen(wallets=wallets)
    # 1 wallet + 3 actions = 4 rows. Cursor 0 -> 1 -> 2 lands on "+ Restore".
    s.on_event(_evt(Button.DOWN))
    s.on_event(_evt(Button.DOWN))
    s.on_event(_evt(Button.A))
    assert s.result is WalletListAction.RESTORE


def test_list_settings_action() -> None:
    """Settings row sits at the bottom and confirms to WalletListAction.SETTINGS."""
    wallets = [_wallet("daily")]
    s = WalletListScreen(wallets=wallets)
    # 1 wallet + 3 actions = 4 rows; the settings row is the last.
    for _ in range(3):
        s.on_event(_evt(Button.DOWN))
    s.on_event(_evt(Button.A))
    assert s.result is WalletListAction.SETTINGS


def test_list_settings_action_on_empty_vault() -> None:
    s = WalletListScreen(wallets=[])
    # 0 wallets + 3 actions: rows are New(0), Restore(1), Settings(2).
    s.on_event(_evt(Button.DOWN))
    s.on_event(_evt(Button.DOWN))
    s.on_event(_evt(Button.A))
    assert s.result is WalletListAction.SETTINGS


def test_list_draws() -> None:
    fb = FrameBuffer()
    wallets = [_wallet(f"w{i}", i) for i in range(5)]
    WalletListScreen(wallets=wallets).draw(fb)


def test_format_label_includes_fingerprint_hex() -> None:
    w = _wallet("daily", idx=0xAB)
    label = WalletListScreen._format_label(w)
    assert "daily" in label
    # First 4 bytes -> 8 hex chars, first 4 of those should appear.
    assert "abacadae"[:8] in label

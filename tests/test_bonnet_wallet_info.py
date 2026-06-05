"""Tests for the read-only WalletInfoScreen.

The screen surfaces a wallet's HD path + fingerprint + word count so
the operator can audit which account a wallet is wired to. It must
never mutate vault state and must terminate on B / A / SELECT.
"""

from __future__ import annotations

from piwallet.bonnet.wallet_info import WalletInfoScreen
from piwallet.core.vault import WalletRecord
from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind


def _evt(b: Button, k: EventKind = EventKind.PRESS) -> Event:
    return Event(button=b, kind=k, at_ms=0)


def _wallet(
    *,
    label: str = "daily",
    fingerprint: bytes = b"\xab\xcd\xef\x01",
    derivation_path: str = "m/44'/236'/0'",
    word_count: int = 12,
    created_at: str = "2026-05-13T08:30:00+00:00",
    network: str = "main",
) -> WalletRecord:
    return WalletRecord(
        id="w-0",
        label=label,
        fingerprint=fingerprint,
        derivation_path=derivation_path,
        word_count=word_count,
        created_at=created_at,
        network=network,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


def test_b_press_returns_back() -> None:
    s = WalletInfoScreen(wallet=_wallet())
    s.on_event(_evt(Button.B))
    assert s.done
    assert s.result == "back"


def test_a_press_returns_back() -> None:
    s = WalletInfoScreen(wallet=_wallet())
    s.on_event(_evt(Button.A))
    assert s.done
    assert s.result == "back"


def test_select_press_returns_back() -> None:
    s = WalletInfoScreen(wallet=_wallet())
    s.on_event(_evt(Button.SELECT))
    assert s.done
    assert s.result == "back"


def test_b_long_is_ignored() -> None:
    s = WalletInfoScreen(wallet=_wallet())
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.done is False
    s.on_event(_evt(Button.B, EventKind.PRESS))
    assert s.done
    assert s.result == "back"


def test_no_events_after_done() -> None:
    s = WalletInfoScreen(wallet=_wallet())
    s.on_event(_evt(Button.A))
    assert s.result == "back"
    s.on_event(_evt(Button.B, EventKind.LONG))
    # Locked in once done.
    assert s.result == "back"


def test_left_right_up_down_are_inert() -> None:
    s = WalletInfoScreen(wallet=_wallet())
    for b in (Button.LEFT, Button.RIGHT, Button.UP, Button.DOWN):
        s.on_event(_evt(b))
    assert not s.done
    assert s.result is None


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def test_draw_runs_without_error() -> None:
    fb = FrameBuffer()
    WalletInfoScreen(wallet=_wallet()).draw(fb)


def test_draw_handles_long_label_via_truncation() -> None:
    fb = FrameBuffer()
    long_label = "a-very-long-wallet-label-that-cannot-fit"
    WalletInfoScreen(wallet=_wallet(label=long_label)).draw(fb)


def test_format_created_at_trims_to_date() -> None:
    s = WalletInfoScreen(wallet=_wallet(created_at="2026-05-13T08:30:00+00:00"))
    assert s._format_created_at(s.wallet.created_at) == "2026-05-13"


def test_format_created_at_handles_no_t_separator() -> None:
    s = WalletInfoScreen(wallet=_wallet())
    assert s._format_created_at("2026-05-13") == "2026-05-13"
    assert s._format_created_at("epoch-marker") == "epoch-mark"


def test_format_network_renders_main_and_test() -> None:
    """Network label is operator-readable; 'test' shouts in caps so it
    can't be confused with a real-money wallet at a glance."""
    assert WalletInfoScreen._format_network("main") == "mainnet"
    assert WalletInfoScreen._format_network("test") == "TESTNET"


def test_format_network_passes_unknown_through() -> None:
    """A future schema value must render as-is rather than crashing."""
    assert WalletInfoScreen._format_network("regtest") == "regtest"


def test_draw_main_and_test_both_render() -> None:
    """Smoke: both networks paint without error and produce different bytes."""
    main_fb = FrameBuffer()
    test_fb = FrameBuffer()
    WalletInfoScreen(wallet=_wallet(network="main")).draw(main_fb)
    WalletInfoScreen(wallet=_wallet(network="test")).draw(test_fb)
    assert main_fb.image.tobytes() != test_fb.image.tobytes()

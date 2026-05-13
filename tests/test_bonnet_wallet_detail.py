"""WalletDetailScreen tests."""

from __future__ import annotations

from piwallet.bonnet.wallet_detail import WalletDetailScreen
from piwallet.core.vault import WalletRecord
from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind


def _evt(b: Button, k: EventKind = EventKind.PRESS, at_ms: int = 0) -> Event:
    return Event(button=b, kind=k, at_ms=at_ms)


def _wallet() -> WalletRecord:
    return WalletRecord(
        id="w-0",
        label="daily",
        fingerprint=b"\x01\x02\x03\x04",
        derivation_path="m/44'/236'/0'",
        word_count=12,
        created_at="2026-05-10T00:00:00+00:00",
    )


def _derive_stub(change: int, index: int) -> str:
    # Returns a sentinel that encodes the inputs, so tests can assert
    # the right (change, index) pair was used.
    return f"addr-{change}-{index}"


def test_initial_state() -> None:
    s = WalletDetailScreen(wallet=_wallet(), derive_address=_derive_stub)
    assert s.index == 0
    assert s.current_address() == "addr-0-0"


def test_right_advances_index() -> None:
    s = WalletDetailScreen(wallet=_wallet(), derive_address=_derive_stub)
    s.on_event(_evt(Button.RIGHT))
    assert s.index == 1
    assert s.current_address() == "addr-0-1"


def test_a_advances_index_same_as_right() -> None:
    s = WalletDetailScreen(wallet=_wallet(), derive_address=_derive_stub)
    s.on_event(_evt(Button.A))
    assert s.index == 1


def test_left_decrements_clamped_at_zero() -> None:
    s = WalletDetailScreen(wallet=_wallet(), derive_address=_derive_stub, index=2)
    s.on_event(_evt(Button.LEFT))
    assert s.index == 1
    s.on_event(_evt(Button.LEFT))
    s.on_event(_evt(Button.LEFT))
    s.on_event(_evt(Button.LEFT))
    assert s.index == 0


def test_select_returns_back() -> None:
    s = WalletDetailScreen(wallet=_wallet(), derive_address=_derive_stub)
    s.on_event(_evt(Button.SELECT))
    assert s.done is True
    assert s.result == "back"


def test_b_press_returns_back() -> None:
    s = WalletDetailScreen(wallet=_wallet(), derive_address=_derive_stub)
    s.on_event(_evt(Button.B, EventKind.PRESS))
    assert s.done is True
    assert s.result == "back"


def test_b_long_exits() -> None:
    s = WalletDetailScreen(wallet=_wallet(), derive_address=_derive_stub)
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.done is True
    assert s.result == "exit"


def test_address_is_cached_per_index() -> None:
    calls: list[tuple[int, int]] = []

    def derive(change: int, index: int) -> str:
        calls.append((change, index))
        return f"a-{change}-{index}"

    s = WalletDetailScreen(wallet=_wallet(), derive_address=derive)
    s.current_address()
    s.current_address()
    s.current_address()
    assert calls == [(0, 0)]  # cached after first call

    s.on_event(_evt(Button.RIGHT))
    s.current_address()
    s.on_event(_evt(Button.LEFT))
    s.current_address()
    assert calls == [(0, 0), (0, 1)]  # both indexes derived once each


def test_draw_renders_qr_without_exception() -> None:
    fb = FrameBuffer()
    s = WalletDetailScreen(wallet=_wallet(), derive_address=_derive_stub)
    s.draw(fb)
    # The drawing should have produced *some* white pixels (QR background).
    saw_white = any(
        fb.image.getpixel((x, y)) == (255, 255, 255)
        for x in range(40, 200, 8)
        for y in range(60, 200, 8)
    )
    assert saw_white, "expected white pixels somewhere from the QR background"

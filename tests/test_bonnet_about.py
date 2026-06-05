"""AboutScreen tests."""

from __future__ import annotations

import pytest

from piwallet.bonnet.about import (
    ABOUT_TAGLINE,
    ABOUT_TWITTER,
    ABOUT_WEBSITE,
    AboutScreen,
    build_about_screen,
)
from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind


def _evt(b: Button, k: EventKind = EventKind.PRESS, at_ms: int = 0) -> Event:
    return Event(button=b, kind=k, at_ms=at_ms)


def test_about_a_or_b_returns_back() -> None:
    s = AboutScreen(
        version="v0.0.0",
        tagline="test",
        website="https://example.com",
        twitter="@PiWalletSV",
        rows=[("Wallets", "0")],
    )
    s.on_event(_evt(Button.A))
    assert s.done is True
    assert s.result == "back"

    s = AboutScreen(
        version="v0.0.0",
        tagline="test",
        website="https://example.com",
        twitter="@PiWalletSV",
        rows=[("Wallets", "0")],
    )
    s.on_event(_evt(Button.B))
    assert s.done is True
    assert s.result == "back"


def test_build_about_screen_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "piwallet.bonnet.about.read_pi_serial",
        lambda: "10000000a1b2c3d4",
    )
    s = build_about_screen(wallet_count=3)
    values = dict(s.rows)
    labels = [k for k, _ in s.rows]
    assert labels == ["Wallets", "Serial", "Host"]
    assert values["Wallets"] == "3"
    assert values["Serial"] == "10000000a1b2c3d4"
    assert s.tagline == ABOUT_TAGLINE
    assert s.website == ABOUT_WEBSITE
    assert s.twitter == ABOUT_TWITTER
    assert s.version.startswith("v")
    assert "Terms" not in labels
    assert "Sleep" not in labels
    assert "Network" not in labels


def test_about_draws() -> None:
    fb = FrameBuffer()
    AboutScreen(
        version="v0.0.0",
        tagline=ABOUT_TAGLINE,
        website=ABOUT_WEBSITE,
        twitter=ABOUT_TWITTER,
        rows=[("Wallets", "1")],
    ).draw(fb)

"""DisclaimerScreen interaction tests."""

from __future__ import annotations

import pytest

from piwallet.firstboot.disclaimer import (
    DEFAULT_DISCLAIMER_PAGES,
    DisclaimerScreen,
)
from piwallet.ui.display import COLOR_BG, FrameBuffer
from piwallet.ui.input import Button, Event, EventKind


def _evt(button: Button, kind: EventKind = EventKind.PRESS, at_ms: int = 0) -> Event:
    return Event(button=button, kind=kind, at_ms=at_ms)


class _FakeClock:
    def __init__(self, start: int = 0) -> None:
        self.now = start

    def __call__(self) -> int:
        return self.now

    def tick(self, ms: int) -> None:
        self.now += ms


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


def test_initial_page_and_done_state() -> None:
    s = DisclaimerScreen()
    assert s.page == 0
    assert s.done is False
    assert s.result is None


def test_right_advances_pages() -> None:
    s = DisclaimerScreen()
    s.on_event(_evt(Button.RIGHT))
    assert s.page == 1
    s.on_event(_evt(Button.RIGHT))
    assert s.page == 2


def test_right_clamps_at_last_page() -> None:
    s = DisclaimerScreen()
    for _ in range(10):
        s.on_event(_evt(Button.RIGHT))
    assert s.page == len(DEFAULT_DISCLAIMER_PAGES) - 1
    assert s.done is False


def test_left_goes_back_and_clamps_at_zero() -> None:
    s = DisclaimerScreen()
    s.on_event(_evt(Button.RIGHT))
    s.on_event(_evt(Button.RIGHT))
    assert s.page == 2
    s.on_event(_evt(Button.LEFT))
    assert s.page == 1
    s.on_event(_evt(Button.LEFT))
    assert s.page == 0
    s.on_event(_evt(Button.LEFT))
    assert s.page == 0


def test_repeat_events_also_advance() -> None:
    """Holding RIGHT down should auto-advance via REPEAT events."""
    s = DisclaimerScreen()
    s.on_event(_evt(Button.RIGHT, EventKind.PRESS))
    assert s.page == 1
    s.on_event(_evt(Button.RIGHT, EventKind.REPEAT, at_ms=420))
    assert s.page == 2


# ---------------------------------------------------------------------------
# Hold-A accept gesture
# ---------------------------------------------------------------------------


def test_hold_a_only_accepts_on_last_page() -> None:
    s = DisclaimerScreen()
    # Long-press A on page 0 must NOT accept.
    s.on_event(_evt(Button.A, EventKind.LONG))
    assert s.done is False
    assert s.result is None
    # Advance to the last page, then long-press A.
    s.on_event(_evt(Button.RIGHT))
    s.on_event(_evt(Button.RIGHT))
    s.on_event(_evt(Button.A, EventKind.PRESS, at_ms=100))
    s.on_event(_evt(Button.A, EventKind.LONG, at_ms=800))
    assert s.done is True
    assert s.result is True


def test_hold_progress_advances_with_time() -> None:
    clock = _FakeClock(start=1_000)
    s = DisclaimerScreen(clock_ms=clock, hold_target_ms=700)
    # Walk to the last page.
    s.on_event(_evt(Button.RIGHT))
    s.on_event(_evt(Button.RIGHT))

    assert s.hold_progress() == 0.0
    s.on_event(_evt(Button.A, EventKind.PRESS, at_ms=clock.now))
    assert s.hold_progress() == pytest.approx(0.0, abs=0.01)

    clock.tick(350)
    assert s.hold_progress() == pytest.approx(0.5, abs=0.01)

    clock.tick(350)
    assert s.hold_progress() == pytest.approx(1.0, abs=0.01)

    # Overshoot is clamped.
    clock.tick(500)
    assert s.hold_progress() == 1.0


def test_hold_progress_resets_on_release() -> None:
    clock = _FakeClock(start=500)
    s = DisclaimerScreen(clock_ms=clock, hold_target_ms=700)
    s.on_event(_evt(Button.RIGHT))
    s.on_event(_evt(Button.RIGHT))
    s.on_event(_evt(Button.A, EventKind.PRESS, at_ms=clock.now))
    clock.tick(200)
    assert s.hold_progress() > 0
    s.on_event(_evt(Button.A, EventKind.RELEASE, at_ms=clock.now))
    assert s.hold_progress() == 0.0


def test_navigation_resets_hold_progress() -> None:
    clock = _FakeClock(start=500)
    s = DisclaimerScreen(clock_ms=clock)
    s.on_event(_evt(Button.RIGHT))
    s.on_event(_evt(Button.RIGHT))
    s.on_event(_evt(Button.A, EventKind.PRESS, at_ms=clock.now))
    clock.tick(300)
    s.on_event(_evt(Button.LEFT))  # back one page
    assert s.hold_progress() == 0.0


# ---------------------------------------------------------------------------
# Bail (long-press B)
# ---------------------------------------------------------------------------


def test_long_b_bails_from_any_page() -> None:
    s = DisclaimerScreen()
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.done is True
    assert s.result is False


# ---------------------------------------------------------------------------
# Rendering smoke
# ---------------------------------------------------------------------------


def test_draw_does_not_raise() -> None:
    fb = FrameBuffer()
    s = DisclaimerScreen()
    s.draw(fb)
    # First page should have some non-background pixels (modal border).
    has_pixels = any(
        fb.image.getpixel((x, y)) != COLOR_BG
        for x in range(0, 240, 8)
        for y in range(0, 240, 8)
    )
    assert has_pixels


def test_last_page_draws_with_hold_progress() -> None:
    fb = FrameBuffer()
    clock = _FakeClock(start=0)
    s = DisclaimerScreen(clock_ms=clock, hold_target_ms=700)
    s.on_event(_evt(Button.RIGHT))
    s.on_event(_evt(Button.RIGHT))
    # Render with no hold; then render mid-hold.
    s.draw(fb)
    s.on_event(_evt(Button.A, EventKind.PRESS, at_ms=clock.now))
    clock.tick(350)
    s.draw(fb)
    # Progress bar pixels should now exist somewhere near the bottom.
    assert s.hold_progress() > 0.4

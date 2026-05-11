"""Widget behavior + smoke-render tests.

These tests check state machines (cursor motion, scroll clamping,
confirm payload routing) and that ``draw()`` runs without error and
produces *some* non-background pixels. We deliberately don't pixel-
match exact glyphs — Pillow's default font can change subtly across
versions — but we do verify regions that should be filled by the
widget (cursor highlight, modal border, progress bar fill).
"""

from __future__ import annotations

import pytest

from piwallet.ui.display import COLOR_ACCENT, COLOR_BG, FrameBuffer, HeadlessDisplay
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.widgets import (
    ListItem,
    ListView,
    Modal,
    ProgressBar,
    _wrap_lines,
    draw_text,
)


def _evt(button: Button, kind: EventKind = EventKind.PRESS, at_ms: int = 0) -> Event:
    return Event(button=button, kind=kind, at_ms=at_ms)


# ---------------------------------------------------------------------------
# ListView
# ---------------------------------------------------------------------------


def test_listview_requires_items() -> None:
    with pytest.raises(ValueError):
        ListView(items=[])


def test_listview_cursor_wraps_with_up_down() -> None:
    lv = ListView(items=[ListItem("A"), ListItem("B"), ListItem("C")])
    assert lv.cursor == 0
    lv.on_event(_evt(Button.DOWN))
    assert lv.cursor == 1
    lv.on_event(_evt(Button.DOWN))
    assert lv.cursor == 2
    lv.on_event(_evt(Button.DOWN))
    assert lv.cursor == 0  # wraps
    lv.on_event(_evt(Button.UP))
    assert lv.cursor == 2  # wraps backwards


def test_listview_skips_disabled_rows() -> None:
    lv = ListView(items=[ListItem("A"), ListItem("B", disabled=True), ListItem("C")])
    lv.on_event(_evt(Button.DOWN))
    assert lv.cursor == 2  # jumped over disabled "B"
    lv.on_event(_evt(Button.DOWN))
    assert lv.cursor == 0


def test_listview_confirm_returns_value() -> None:
    lv = ListView(items=[
        ListItem("Send", value="send"),
        ListItem("Receive", value="receive"),
    ])
    lv.on_event(_evt(Button.DOWN))
    assert lv.confirmed is None
    lv.on_event(_evt(Button.A))
    assert lv.confirmed == "receive"


def test_listview_confirm_ignored_for_disabled_row() -> None:
    lv = ListView(items=[ListItem("locked", disabled=True), ListItem("ok", value="ok")])
    # Cursor stays on row 0 (disabled). Confirm must be a no-op.
    lv.on_event(_evt(Button.A))
    assert lv.confirmed is None


def test_listview_scrolls_when_cursor_leaves_window() -> None:
    items = [ListItem(f"item-{i}") for i in range(20)]
    lv = ListView(items=items, visible_rows=5, title="")
    # Move cursor past the visible window and make sure scroll follows.
    for _ in range(7):
        lv.on_event(_evt(Button.DOWN))
    assert lv.cursor == 7
    assert lv._scroll == 3  # 7 - 5 + 1


def test_listview_draw_paints_pixels() -> None:
    fb = FrameBuffer()
    lv = ListView(items=[ListItem("Alpha"), ListItem("Bravo")], title="Wallets")
    lv.draw(fb)
    # Some non-background pixel must exist (cursor highlight row).
    found = False
    for x in range(0, 240, 8):
        for y in range(0, 240, 8):
            if fb.image.getpixel((x, y)) != COLOR_BG:
                found = True
                break
        if found:
            break
    assert found, "ListView.draw produced an all-black frame"


# ---------------------------------------------------------------------------
# Modal
# ---------------------------------------------------------------------------


def test_modal_draw_paints_border_accent() -> None:
    fb = FrameBuffer()
    Modal(title="Warning", body="Hold A to accept", footer="B = back").draw(fb)
    # The accent-coloured border should appear somewhere on the top edge
    # of the card (y = 12, between x=14..226).
    border_hits = sum(
        1 for x in range(14, 226) if fb.image.getpixel((x, 12)) == COLOR_ACCENT
    )
    assert border_hits > 100, f"expected an accent border line, got {border_hits} hits"


def test_modal_wraps_long_body_safely() -> None:
    long = (
        "The mnemonic shown on the previous screen is the ONLY way to "
        "recover this wallet. Photographs and screenshots leak."
    )
    fb = FrameBuffer()
    Modal(title="Restore", body=long).draw(fb)
    # Just verify no exceptions; pixel checks are too fragile for fonts.


# ---------------------------------------------------------------------------
# ProgressBar
# ---------------------------------------------------------------------------


def test_progress_bar_clamps_value() -> None:
    pb = ProgressBar(value=999, total=100)
    pb.set_progress(120)
    assert pb.value == 100
    pb.set_progress(-50)
    assert pb.value == 0


def test_progress_bar_updates_total() -> None:
    pb = ProgressBar()
    pb.set_progress(5, total=10)
    assert pb.total == 10
    assert pb.value == 5


def test_progress_bar_draw_fills_proportionally() -> None:
    fb = FrameBuffer()
    pb = ProgressBar(label="Signing", value=0, total=100, y=100)
    pb.set_progress(50)
    pb.draw(fb)
    # The fill is the configured colour (default COLOR_OK = green).
    # Sample a point well inside the left half of the bar — it must
    # be the fill colour. A point well past the right half must NOT be.
    left_sample = fb.image.getpixel((40, 110))
    right_sample = fb.image.getpixel((220, 110))
    assert left_sample != COLOR_BG
    assert right_sample != left_sample  # right edge isn't filled


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_wrap_lines_respects_newlines_and_max_chars() -> None:
    out = _wrap_lines("hello world\nthis is a longer line", max_chars=10)
    assert all(len(line) <= 10 for line in out)
    # An explicit newline preserves a paragraph break.
    assert any(line == "" for line in out) is False  # leading blanks trimmed


def test_wrap_lines_hard_breaks_oversized_word() -> None:
    out = _wrap_lines("abcdefghijklmnop", max_chars=5)
    # Should be split into 5-char chunks plus the remainder.
    assert all(len(line) <= 5 for line in out)
    assert "".join(out) == "abcdefghijklmnop"


def test_draw_text_does_not_raise_for_empty_string() -> None:
    fb = FrameBuffer()
    draw_text(fb, 10, 10, "", size=12)


# ---------------------------------------------------------------------------
# Display integration smoke
# ---------------------------------------------------------------------------


def test_widget_draws_can_flip_to_headless_display() -> None:
    display = HeadlessDisplay()
    fb = FrameBuffer()
    lv = ListView(items=[ListItem("A"), ListItem("B")], title="Test")
    lv.draw(fb)
    display.flip(fb)
    assert display.flip_count == 1
    assert display.image.size == (240, 240)

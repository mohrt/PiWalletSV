"""WalletLabelEntryScreen tests."""

from __future__ import annotations

from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.label_entry import (
    LABEL_MAX_CHARS,
    WalletLabelEntryScreen,
)


def _evt(b: Button, k: EventKind = EventKind.PRESS, at_ms: int = 0) -> Event:
    return Event(button=b, kind=k, at_ms=at_ms)


# ---------------------------------------------------------------------------
# Construction & defaults
# ---------------------------------------------------------------------------


def test_empty_default_seeds_single_letter() -> None:
    s = WalletLabelEntryScreen()
    assert s.buffer == ["a"]
    assert s.cursor == 0
    assert s.typed_text() == "a"


def test_suggested_default_seeds_buffer() -> None:
    s = WalletLabelEntryScreen(suggested_default="wallet-9")
    assert s.typed_text() == "wallet-9"
    # Cursor lands on the last letter so the user can extend or edit it.
    assert s.cursor == len("wallet-9") - 1


def test_suggested_default_folded_lower() -> None:
    s = WalletLabelEntryScreen(suggested_default="POOL")
    assert s.typed_text() == "pool"


def test_truncates_default_to_max_len() -> None:
    s = WalletLabelEntryScreen(max_len=4, suggested_default="abcdefghi")
    assert s.typed_text() == "abcd"
    assert s.cursor == 3


# ---------------------------------------------------------------------------
# Letter cycling (UP / DOWN)
# ---------------------------------------------------------------------------


def test_down_cycles_letter_at_cursor() -> None:
    s = WalletLabelEntryScreen()
    assert s.buffer[s.cursor] == "a"
    s.on_event(_evt(Button.DOWN))
    assert s.buffer[s.cursor] == "b"
    s.on_event(_evt(Button.DOWN))
    assert s.buffer[s.cursor] == "c"


def test_up_cycles_back_with_wrap() -> None:
    s = WalletLabelEntryScreen()
    s.on_event(_evt(Button.UP))
    # First glyph is " ", so cycling up from "a" goes to " " (space).
    assert s.buffer[s.cursor] == " "


def test_up_repeat_event_also_cycles() -> None:
    s = WalletLabelEntryScreen()
    s.on_event(_evt(Button.UP, EventKind.REPEAT))
    assert s.buffer[s.cursor] == " "


# ---------------------------------------------------------------------------
# Cursor movement (LEFT / RIGHT)
# ---------------------------------------------------------------------------


def test_right_moves_cursor_to_new_slot() -> None:
    s = WalletLabelEntryScreen(suggested_default="ab")
    assert s.cursor == 1
    s.on_event(_evt(Button.RIGHT))
    # Cursor lands on the trailing "new slot".
    assert s.cursor == 2
    assert len(s.buffer) == 2  # buffer not yet grown
    s.on_event(_evt(Button.DOWN))
    # Auto-append a letter and cycle it: " " -> "a"
    assert s.buffer == ["a", "b", "a"]
    assert s.cursor == 2


def test_right_blocked_at_max_len() -> None:
    txt = "a" * LABEL_MAX_CHARS
    s = WalletLabelEntryScreen(max_len=LABEL_MAX_CHARS, suggested_default=txt)
    # Buffer already at max_len; cursor capped at last letter.
    assert s.cursor == LABEL_MAX_CHARS - 1
    s.on_event(_evt(Button.RIGHT))
    assert s.cursor == LABEL_MAX_CHARS - 1
    assert len(s.buffer) == LABEL_MAX_CHARS


def test_left_moves_cursor_left() -> None:
    s = WalletLabelEntryScreen(suggested_default="abc")
    assert s.cursor == 2
    s.on_event(_evt(Button.LEFT))
    assert s.cursor == 1
    s.on_event(_evt(Button.LEFT))
    assert s.cursor == 0
    s.on_event(_evt(Button.LEFT))
    assert s.cursor == 0  # clamped


def test_cycle_at_existing_letter_does_not_grow_buffer() -> None:
    s = WalletLabelEntryScreen(suggested_default="abc")
    assert s.cursor == 2
    s.on_event(_evt(Button.DOWN))
    assert s.buffer == ["a", "b", "d"]


# ---------------------------------------------------------------------------
# Backspace / DEL (B PRESS)
# ---------------------------------------------------------------------------


def test_b_press_deletes_letter_at_cursor_mid_word() -> None:
    """Cursor on an interior letter -> delete it; next letter slides in."""
    s = WalletLabelEntryScreen(suggested_default="alpha")
    s.cursor = 2  # on 'p'
    s.on_event(_evt(Button.B, EventKind.PRESS))
    assert s.buffer == ["a", "l", "h", "a"]
    assert s.cursor == 2  # cursor stays in place; 'h' is now under it


def test_b_press_deletes_letter_at_cursor_last() -> None:
    """Cursor on last letter -> delete it; cursor decrements to new last."""
    s = WalletLabelEntryScreen(suggested_default="alpha")
    assert s.cursor == 4
    s.on_event(_evt(Button.B, EventKind.PRESS))
    assert s.buffer == ["a", "l", "p", "h"]
    assert s.cursor == 3  # clamped to the new last index


def test_b_press_at_cursor_zero_deletes_first_letter() -> None:
    """B at cursor=0 with a multi-letter buffer deletes the first letter."""
    s = WalletLabelEntryScreen(suggested_default="ab")
    s.on_event(_evt(Button.LEFT))  # cursor -> 0
    assert s.cursor == 0
    s.on_event(_evt(Button.B, EventKind.PRESS))
    assert s.buffer == ["b"]
    assert s.cursor == 0
    assert not s.done


def test_b_press_from_new_slot_deletes_last_letter() -> None:
    s = WalletLabelEntryScreen(suggested_default="ab")
    s.on_event(_evt(Button.RIGHT))  # cursor -> 2 (new slot)
    assert s.cursor == 2
    s.on_event(_evt(Button.B, EventKind.PRESS))
    assert s.buffer == ["a"]
    assert s.cursor == 0  # always land on a real letter after DEL


def test_b_press_with_single_letter_is_noop() -> None:
    """The editor always keeps at least one letter; B with a single letter is a no-op."""
    s = WalletLabelEntryScreen()  # buffer=['a'], cursor=0
    s.on_event(_evt(Button.B, EventKind.PRESS))
    assert s.buffer == ["a"]
    assert s.cursor == 0
    assert not s.done


def test_b_long_cancels_with_none() -> None:
    s = WalletLabelEntryScreen()
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.done is True
    assert s.result is None


# ---------------------------------------------------------------------------
# Save / cancel
# ---------------------------------------------------------------------------


def test_a_saves_immediately() -> None:
    """A commits the typed name in one step (no confirm phase)."""
    s = WalletLabelEntryScreen(suggested_default="cold")
    s.on_event(_evt(Button.A))
    assert s.done is True
    assert s.result == "cold"


def test_select_saves_immediately() -> None:
    s = WalletLabelEntryScreen(suggested_default="cold")
    s.on_event(_evt(Button.SELECT))
    assert s.done is True
    assert s.result == "cold"


def test_blank_after_strip_blocks_save() -> None:
    s = WalletLabelEntryScreen()
    # Cycle the only letter to a space.
    s.on_event(_evt(Button.UP))
    assert s.buffer == [" "]
    s.on_event(_evt(Button.A))
    assert not s.done
    assert s.transient_error == "Can't be blank"


def test_save_strips_trailing_space() -> None:
    s = WalletLabelEntryScreen(suggested_default="cold")
    s.on_event(_evt(Button.RIGHT))  # cursor -> new slot
    # Append a literal space directly to verify save stripping.
    s.buffer.append(" ")
    s.on_event(_evt(Button.A))
    assert s.done is True
    assert s.result == "cold"


# ---------------------------------------------------------------------------
# Rendering smoke
# ---------------------------------------------------------------------------


def test_draw_edit_smoke() -> None:
    fb = FrameBuffer()
    WalletLabelEntryScreen(suggested_default="cold").draw(fb)


def test_draw_long_label_does_not_crash() -> None:
    fb = FrameBuffer()
    s = WalletLabelEntryScreen(suggested_default="abcdefghijklmnopqrstuvwx")
    s.draw(fb)

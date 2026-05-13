"""WordEntryScreen + MnemonicEntryScreen tests."""

from __future__ import annotations

import pytest

from piwallet.core import mnemonic as mnem
from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.word_entry import MnemonicEntryScreen, WordEntryScreen


def _evt(b: Button, k: EventKind = EventKind.PRESS, at_ms: int = 0) -> Event:
    return Event(button=b, kind=k, at_ms=at_ms)


def _type_letter(screen: WordEntryScreen, letter: str) -> None:
    """Cycle the candidate to ``letter`` (DOWN ``n`` times)."""
    target = ord(letter) - ord("a")
    current = ord(screen.candidate) - ord("a")
    delta = (target - current) % 26
    for _ in range(delta):
        screen.on_event(_evt(Button.DOWN))


def _type_word(screen: WordEntryScreen, word: str) -> None:
    """Drive the screen through ``word``: for each letter, cycle then RIGHT.

    Leaves the LAST letter as the active candidate (so callers can press
    A to confirm the word).
    """
    for i, ch in enumerate(word):
        _type_letter(screen, ch)
        if i < len(word) - 1:
            screen.on_event(_evt(Button.RIGHT))


# ---------------------------------------------------------------------------
# Construction & invariants
# ---------------------------------------------------------------------------


def test_default_state() -> None:
    s = WordEntryScreen()
    assert s.prefix == ""
    assert s.candidate == "a"
    assert s.done is False
    assert s.result is None
    assert s.typed_text() == "a"


def test_invalid_candidate_rejected() -> None:
    with pytest.raises(ValueError):
        WordEntryScreen(candidate="ab")
    with pytest.raises(ValueError):
        WordEntryScreen(candidate="A")
    with pytest.raises(ValueError):
        WordEntryScreen(candidate="1")


# ---------------------------------------------------------------------------
# Letter cycling
# ---------------------------------------------------------------------------


def test_down_cycles_forward() -> None:
    s = WordEntryScreen()
    s.on_event(_evt(Button.DOWN))
    assert s.candidate == "b"
    s.on_event(_evt(Button.DOWN))
    assert s.candidate == "c"


def test_up_cycles_back_with_wrap() -> None:
    s = WordEntryScreen()
    s.on_event(_evt(Button.UP))
    assert s.candidate == "z"


def test_up_repeat_fires_on_repeat_event() -> None:
    s = WordEntryScreen()
    s.on_event(_evt(Button.UP, EventKind.REPEAT))
    assert s.candidate == "z"


# ---------------------------------------------------------------------------
# Commit + backspace
# ---------------------------------------------------------------------------


def test_right_commits_candidate_and_opens_a() -> None:
    s = WordEntryScreen()
    _type_letter(s, "b")
    s.on_event(_evt(Button.RIGHT))
    assert s.prefix == "b"
    assert s.candidate == "a"


def test_left_backspace_reopens_last_committed() -> None:
    s = WordEntryScreen()
    _type_letter(s, "b")
    s.on_event(_evt(Button.RIGHT))
    assert (s.prefix, s.candidate) == ("b", "a")
    s.on_event(_evt(Button.LEFT))
    assert (s.prefix, s.candidate) == ("", "b")


def test_left_with_empty_prefix_resets_candidate_to_a() -> None:
    s = WordEntryScreen(candidate="z")
    s.on_event(_evt(Button.LEFT))
    assert s.prefix == ""
    assert s.candidate == "a"


def test_b_press_clears_in_progress_word() -> None:
    s = WordEntryScreen()
    _type_word(s, "abc")
    assert s.prefix == "ab"
    s.on_event(_evt(Button.B, EventKind.PRESS))
    assert s.prefix == ""
    assert s.candidate == "a"
    assert s.done is False


def test_b_long_cancels_flow() -> None:
    s = WordEntryScreen()
    _type_letter(s, "z")
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.done is True
    assert s.result is None


def test_select_ambiguous_enters_pick_list() -> None:
    s = WordEntryScreen()
    _type_word(s, "ab")
    assert s.match_state() == "many"
    s.on_event(_evt(Button.SELECT))
    assert s.pick_mode is True
    assert not s.done


def test_select_exact_word_confirms_not_pick() -> None:
    s = WordEntryScreen()
    _type_word(s, "abandon")
    assert s.match_state() == "exact"
    s.on_event(_evt(Button.SELECT))
    assert not s.pick_mode
    assert s.done and s.result == "abandon"


def test_select_unique_completion_enters_pick() -> None:
    s = WordEntryScreen()
    _type_word(s, "abi")
    assert s.match_state() == "one"
    s.on_event(_evt(Button.SELECT))
    assert s.pick_mode


def test_pick_mode_navigation_and_confirm() -> None:
    s = WordEntryScreen()
    _type_word(s, "ab")
    s.on_event(_evt(Button.SELECT))
    matches = s.stem_matches()
    target_idx = matches.index("ability")
    for _ in range(target_idx):
        s.on_event(_evt(Button.DOWN))
    s.on_event(_evt(Button.A))
    assert s.done and s.result == "ability"


def test_pick_mode_left_returns_without_confirm() -> None:
    s = WordEntryScreen()
    _type_word(s, "ab")
    s.on_event(_evt(Button.SELECT))
    assert s.pick_mode
    s.on_event(_evt(Button.LEFT))
    assert not s.pick_mode
    assert not s.done


def test_pick_select_exits_pick_mode() -> None:
    s = WordEntryScreen()
    _type_word(s, "ab")
    s.on_event(_evt(Button.SELECT))
    assert s.pick_mode
    s.on_event(_evt(Button.SELECT))
    assert not s.pick_mode


def test_draw_pick_mode_smoke() -> None:
    fb = FrameBuffer()
    s = WordEntryScreen()
    _type_word(s, "ab")
    s.on_event(_evt(Button.SELECT))
    s.draw(fb)


# ---------------------------------------------------------------------------
# Match state classification
# ---------------------------------------------------------------------------


def test_match_state_exact_word() -> None:
    s = WordEntryScreen()
    _type_word(s, "abandon")
    assert s.typed_text() == "abandon"
    assert s.match_state() == "exact"


def test_match_state_unique_completion() -> None:
    # "abi" is the only BIP39 word starting with "abi" -> "ability".
    s = WordEntryScreen()
    _type_word(s, "abi")
    assert s.match_state() == "one"
    assert s.stem_matches() == ["ability"]


def test_match_state_many() -> None:
    s = WordEntryScreen()
    _type_word(s, "ab")
    assert s.match_state() == "many"
    stem = s.stem_matches()
    assert len(stem) > 8  # not just the truncated preview slice
    assert stem[0].startswith("ab")


def test_match_state_none() -> None:
    # "zz" is not a BIP39 prefix.
    s = WordEntryScreen()
    _type_word(s, "zz")
    assert s.match_state() == "none"
    assert s.stem_matches() == []


def test_ma_preview_includes_tail_words_like_maze() -> None:
    """Long ``ma`` stem is last alphabetically; bonnet preview must show tail."""
    s = WordEntryScreen()
    _type_word(s, "ma")
    assert s.match_state() == "many"
    stem = s.stem_matches()
    assert stem[-1] == "maze"
    word_rows = [txt for kind, txt in s.match_preview_rows() if kind == "word"]
    assert "maze" in word_rows


def test_match_preview_gap_when_stem_truncated() -> None:
    s = WordEntryScreen()
    _type_word(s, "ma")
    kinds = [k for k, _ in s.match_preview_rows()]
    assert "gap" in kinds


# ---------------------------------------------------------------------------
# Confirmation behaviour
# ---------------------------------------------------------------------------


def test_a_accepts_exact_bip39_word() -> None:
    s = WordEntryScreen()
    _type_word(s, "abandon")
    s.on_event(_evt(Button.A))
    assert s.done is True
    assert s.result == "abandon"


def test_a_accepts_unique_completion() -> None:
    s = WordEntryScreen()
    # "abi" is the only BIP39 stem leading to "ability".
    _type_word(s, "abi")
    s.on_event(_evt(Button.A))
    assert s.done is True
    assert s.result == "ability"


def test_a_ignored_with_ambiguous_prefix() -> None:
    s = WordEntryScreen()
    _type_word(s, "ab")  # many matches
    s.on_event(_evt(Button.A))
    assert s.done is False
    assert s.result is None


def test_a_ignored_with_invalid_prefix() -> None:
    s = WordEntryScreen()
    _type_word(s, "zz")
    s.on_event(_evt(Button.A))
    assert s.done is False


# ---------------------------------------------------------------------------
# Rendering smoke
# ---------------------------------------------------------------------------


def test_draw_default_state() -> None:
    fb = FrameBuffer()
    WordEntryScreen(title="Word 3 of 12").draw(fb)


def test_draw_with_matches() -> None:
    fb = FrameBuffer()
    s = WordEntryScreen(title="Word 1 of 12")
    _type_word(s, "abandon")
    s.draw(fb)


def test_draw_with_no_match() -> None:
    fb = FrameBuffer()
    s = WordEntryScreen()
    _type_word(s, "zz")
    s.draw(fb)


# ---------------------------------------------------------------------------
# MnemonicEntryScreen (multi-word driver)
# ---------------------------------------------------------------------------


@pytest.fixture()
def real_12_word_phrase() -> list[str]:
    phrase = mnem.generate(12)
    return phrase.split()


def _drive_word(screen: MnemonicEntryScreen, word: str) -> None:
    """Drive the embedded WordEntryScreen through `word` and confirm."""
    _type_word(screen.current, word)
    screen.on_event(_evt(Button.A))


def _confirm_restore_review(screen: MnemonicEntryScreen) -> None:
    """On restore review: highlight Confirm wallet and activate."""
    assert screen.phase == "review"
    assert screen.review_view is not None
    rv = screen.review_view
    rv.cursor = len(rv.items) - 1
    assert not rv.items[-1].disabled
    screen.on_event(_evt(Button.A))


def test_restore_via_pick_single_letter_stem(real_12_word_phrase: list[str]) -> None:
    s = MnemonicEntryScreen(word_count=12, mode="restore")
    for target in real_12_word_phrase:
        we = s.current
        _type_letter(we, target[0])
        s.on_event(_evt(Button.SELECT))
        assert we.pick_mode
        picks = we.stem_matches()
        idx = picks.index(target)
        for _ in range(idx):
            s.on_event(_evt(Button.DOWN))
        s.on_event(_evt(Button.A))
    assert s.phase == "review"
    _confirm_restore_review(s)
    assert s.done is True
    assert s.result == " ".join(real_12_word_phrase)


def test_restore_mode_accepts_valid_phrase(real_12_word_phrase: list[str]) -> None:
    s = MnemonicEntryScreen(word_count=12, mode="restore")
    for w in real_12_word_phrase:
        _drive_word(s, w)
    assert s.phase == "review"
    assert s.mnemonic_checksum_ok()
    _confirm_restore_review(s)
    assert s.done is True
    assert s.result == " ".join(real_12_word_phrase)
    assert s.error is None


def test_restore_mode_invalid_checksum_review_then_cancel() -> None:
    # Each word is valid BIP39 but the phrase checksum fails (canonical
    # valid abandoned phrase ends with "about").
    bad = ["abandon"] * 12
    s = MnemonicEntryScreen(word_count=12, mode="restore")
    for w in bad:
        _drive_word(s, w)
    assert not s.done
    assert s.phase == "review"
    assert not s.mnemonic_checksum_ok()
    assert s.review_view is not None
    assert s.review_view.items[-1].disabled
    assert "✗" in s.review_view.title
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.done is True
    assert s.result is None


def test_restore_long_left_goes_back_one_word(real_12_word_phrase: list[str]) -> None:
    s = MnemonicEntryScreen(word_count=12, mode="restore")
    _drive_word(s, real_12_word_phrase[0])
    assert len(s.words) == 1
    s.on_event(_evt(Button.LEFT, EventKind.LONG))
    assert s.words == []
    assert s.current.title == "Word 1 of 12"


def test_restore_review_edit_word_fixes_checksum() -> None:
    """Invalid phrase becomes valid after editing one slot from review."""
    # Canonical test mnemonic (valid checksum).
    valid_words = ["abandon"] * 11 + ["about"]
    valid_phrase = " ".join(valid_words)

    s = MnemonicEntryScreen(word_count=12, mode="restore")
    for w in ["abandon"] * 12:
        _drive_word(s, w)
    assert s.phase == "review"
    assert not s.mnemonic_checksum_ok()
    for _ in range(11):
        s.on_event(_evt(Button.DOWN))
    assert s.review_view is not None
    assert s.review_view.cursor == 11
    s.on_event(_evt(Button.A))
    assert s.phase == "edit"
    _drive_word(s, "about")
    assert s.phase == "review"
    assert s.words == valid_words
    assert s.mnemonic_checksum_ok()
    assert "✓" in (s.review_view.title if s.review_view else "")
    _confirm_restore_review(s)
    assert s.done and s.result == valid_phrase


def test_restore_mode_user_cancel_via_long_b(real_12_word_phrase: list[str]) -> None:
    s = MnemonicEntryScreen(word_count=12, mode="restore")
    _drive_word(s, real_12_word_phrase[0])
    # Mid-flow long-B from the next word cancels.
    s.current.on_event(_evt(Button.B, EventKind.LONG))
    # The parent must consume the cascade.
    s.on_event(_evt(Button.B, EventKind.LONG))  # idempotent if already done
    # WordEntryScreen.long-B sets done=True with result=None, which the
    # parent observes on the next event; trigger that consumption by
    # feeding a benign event:
    s.on_event(_evt(Button.UP))
    assert s.done is True
    assert s.result is None


def test_create_confirm_accepts_matching_retype(real_12_word_phrase: list[str]) -> None:
    s = MnemonicEntryScreen(
        word_count=12,
        mode="create-confirm",
        expected=real_12_word_phrase,
    )
    for w in real_12_word_phrase:
        _drive_word(s, w)
    assert s.done is True
    assert s.result == " ".join(real_12_word_phrase)
    assert s.error is None


def test_create_confirm_flags_word_mismatch(real_12_word_phrase: list[str]) -> None:
    # User types the wrong word at position 0.
    expected = real_12_word_phrase
    wrong = "zoo" if expected[0] != "zoo" else "abandon"

    s = MnemonicEntryScreen(
        word_count=12,
        mode="create-confirm",
        expected=expected,
    )
    _drive_word(s, wrong)
    assert s.done is True
    assert s.result is None
    assert s.error is not None
    assert "mismatch" in s.error.lower()


def test_create_confirm_requires_expected() -> None:
    with pytest.raises(ValueError):
        MnemonicEntryScreen(word_count=12, mode="create-confirm")


def test_create_confirm_rejects_bad_expected_word() -> None:
    with pytest.raises(ValueError):
        MnemonicEntryScreen(
            word_count=12,
            mode="create-confirm",
            expected=["notabip39word"] + (["abandon"] * 11),
        )


def test_word_count_validation() -> None:
    with pytest.raises(ValueError):
        MnemonicEntryScreen(word_count=15)


def test_draw_delegates_to_current_word(real_12_word_phrase: list[str]) -> None:
    fb = FrameBuffer()
    s = MnemonicEntryScreen(word_count=12, mode="restore")
    s.draw(fb)  # no exception, first word screen
    _drive_word(s, real_12_word_phrase[0])
    s.draw(fb)  # second word screen

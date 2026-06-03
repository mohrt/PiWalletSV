"""Bonnet BIP39 word entry.

Single-word entry screen used inside the mnemonic create-confirm and
restore flows. Reusable on its own (e.g. for unit tests, future
"change label" flows, etc.).

Controls (type mode)
--------------------
=========  =================================================================
UP         Cycle candidate letter back  (a -> z -> y -> ... -> a).
DOWN       Cycle candidate letter fwd   (a -> b -> c -> ... -> z -> a).
LEFT       Move cursor back one letter (no delete). No-op at the first
           letter.
RIGHT      Move cursor forward; at the end of the word, append a new
           letter slot starting at ``a``.
A          Select the word if exact or uniquely determined; if 2+ stem
           matches, open pick mode.
B PRESS    Delete the letter under the cursor and move back one slot.
B LONG     Cancel the whole flow (result=None, done=True).

Mnemonic restore (``MnemonicEntryScreen`` in ``restore`` mode) adds a
post-entry **review** list (checksum banner + per-word edit). During
entry, **L** on the first letter (or **hold L** anywhere) reopens the
previous word for editing.

Controls (pick mode)
--------------------
=========  =================================================================
UP/DOWN    Move highlight through every BIP39 word matching the typed stem
           (wraps at the ends).
A          Select the highlighted word.
B          Return to type mode (typed stem preserved). No cancel from here.

Design note
-----------
Earlier sketches had UP/DOWN navigate the filtered match list and
LEFT/RIGHT cycle letters. On a single-stick joystick those axes
collide -- the user can't tell whether a press will move the cursor
or change a letter -- so we picked an alphabet-knob model that uses
every input distinctly.

The on-screen hints are alphabetical (see :meth:`match_preview_rows`):
many stems show the first three and **last seven** completions so late-alphabet
words such as ``maze`` stay visible during long shared prefixes such as ``ma``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from piwallet.core.mnemonic import BIP39_WORDLIST, words_starting_with
from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DANGER,
    COLOR_DIM,
    COLOR_FG,
    COLOR_OK,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    FrameBuffer,
)
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.widgets import ListItem, ListView, draw_text, text_bbox

#: When many words share the same stem we show first :data:`MATCH_PREVIEW_HEAD`
#: and last :data:`MATCH_PREVIEW_TAIL` alphabetically, with an omission line in
#: between (otherwise ``maze`` never appears among the ``ma…`` completions).
MATCH_PREVIEW_HEAD: int = 3
MATCH_PREVIEW_TAIL: int = 7

#: How many match-list rows to show in pick mode (see :meth:`draw`).
PICK_VISIBLE_LINES: int = 7

#: Single-line entry font size — must stay in sync with :meth:`_draw_type_mode` geometry.
_MAIN_ENTRY_FONT: int = 18

#: A frozen set for O(1) "is this a real BIP39 word?" checks.
_BIP39_WORD_SET: frozenset[str] = frozenset(BIP39_WORDLIST)


@dataclass
class WordEntryScreen:
    """Type one BIP39 word.

    On confirmation (A button) ``result`` is set to the chosen BIP39
    word and ``done`` becomes True. On cancel (long B) ``result`` is
    ``None`` and ``done`` is True.
    """

    title: str = "Word"
    letters: list[str] = field(default_factory=lambda: ["a"])
    cursor: int = 0
    done: bool = False
    result: str | None = None
    #: For the create-confirm flow, the caller can pass the expected
    #: word; the screen does NOT use this to gate input -- the caller
    #: validates ``result`` after the screen completes. We surface it
    #: in the title line as "Word N of M" when the caller wants a
    #: progress hint without leaking the expected word.
    expected_position: int | None = None
    #: When True, footer mentions hold-LEFT to reopen the previous slot
    #: (used by :class:`MnemonicEntryScreen` during restore entry).
    show_hold_left_prev_hint: bool = False
    pick_mode: bool = False
    pick_index: int = 0

    def __post_init__(self) -> None:
        if not self.letters:
            self.letters = ["a"]
        if self.cursor < 0 or self.cursor >= len(self.letters):
            raise ValueError("cursor out of range for letters")
        for ch in self.letters:
            if not (isinstance(ch, str) and len(ch) == 1):
                raise ValueError("each letter must be a single character")
            if not ch.isalpha() or not ch.islower():
                raise ValueError("letters must be lowercase a-z")

    @property
    def prefix(self) -> str:
        """Letters before the cursor (read-only compat for tests)."""
        return "".join(self.letters[: self.cursor])

    @property
    def candidate(self) -> str:
        """Letter under the cursor (read-only compat for tests)."""
        return self.letters[self.cursor]

    # -- input ---------------------------------------------------------

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        if self.pick_mode:
            self._on_event_pick(event)
            return
        b = event.button
        k = event.kind
        if b == Button.UP and k in (EventKind.PRESS, EventKind.REPEAT):
            self._cycle(-1)
        elif b == Button.DOWN and k in (EventKind.PRESS, EventKind.REPEAT):
            self._cycle(+1)
        elif b == Button.LEFT and k in (EventKind.PRESS, EventKind.REPEAT):
            self._move_left()
        elif b == Button.RIGHT and k in (EventKind.PRESS, EventKind.REPEAT):
            self._move_right()
        elif b == Button.A and k == EventKind.PRESS:
            self._confirm()
        elif b == Button.B and k == EventKind.PRESS:
            self._delete_and_back()
        elif b == Button.B and k == EventKind.LONG:
            self._exit_pick_mode()
            self.done = True
            self.result = None

    def _exit_pick_mode(self) -> None:
        self.pick_mode = False

    def _enter_pick_mode(self) -> None:
        stem = self.stem_matches()
        if not stem:
            return
        self.pick_mode = True
        self.pick_index = 0

    def _pick_first_visible(self) -> int:
        m = self.stem_matches()
        vh = PICK_VISIBLE_LINES
        n = len(m)
        if n <= vh:
            return 0
        half = vh // 2
        first = self.pick_index - half
        return max(0, min(first, n - vh))

    def _on_event_pick(self, event: Event) -> None:
        b = event.button
        k = event.kind
        m = self.stem_matches()
        if not m:
            self._exit_pick_mode()
            return
        n = len(m)
        self.pick_index %= n

        if b == Button.B and k in (EventKind.PRESS, EventKind.LONG):
            self._exit_pick_mode()
            return

        if b == Button.UP and k in (EventKind.PRESS, EventKind.REPEAT):
            self.pick_index = (self.pick_index - 1) % n
            return
        if b == Button.DOWN and k in (EventKind.PRESS, EventKind.REPEAT):
            self.pick_index = (self.pick_index + 1) % n
            return
        if b == Button.RIGHT and k in (EventKind.PRESS, EventKind.REPEAT):
            # Letter commits are disabled during pick navigation.
            return
        if b == Button.A and k == EventKind.PRESS:
            self.done = True
            self.result = m[self.pick_index]

    def _cycle(self, delta: int) -> None:
        ch = self.letters[self.cursor]
        idx = (ord(ch) - ord("a") + delta) % 26
        self.letters[self.cursor] = chr(ord("a") + idx)

    def _move_left(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1

    def _move_right(self) -> None:
        if self.cursor < len(self.letters) - 1:
            self.cursor += 1
        else:
            self.letters.append("a")
            self.cursor = len(self.letters) - 1

    def _delete_and_back(self) -> None:
        self._exit_pick_mode()
        if len(self.letters) == 1:
            self.letters[0] = "a"
            self.cursor = 0
            return
        del self.letters[self.cursor]
        if self.cursor > 0:
            self.cursor -= 1

    def _confirm(self) -> None:
        word = self.typed_text()
        if word in _BIP39_WORD_SET:
            self.done = True
            self.result = word
            return
        all_m = self.stem_matches()
        if len(all_m) == 1:
            self.done = True
            self.result = all_m[0]
            return
        if len(all_m) >= 2:
            self._enter_pick_mode()

    # -- introspection -------------------------------------------------

    def typed_text(self) -> str:
        """All letters in the buffer (full in-progress word)."""
        return "".join(self.letters)

    def stem_matches(self) -> list[str]:
        """Every BIP39 word starting with :meth:`typed_text` (long stems ok)."""
        return words_starting_with(self.typed_text())

    def match_preview_rows(self) -> list[tuple[Literal["word", "gap"], str]]:
        """Rows to paint under the status line — word rows plus optional omission."""
        stem = self.stem_matches()
        if not stem:
            return []
        cap = MATCH_PREVIEW_HEAD + MATCH_PREVIEW_TAIL
        if len(stem) <= cap:
            return [("word", w) for w in stem]
        omit_count = len(stem) - cap
        rows: list[tuple[Literal["word", "gap"], str]] = [
            ("word", w) for w in stem[:MATCH_PREVIEW_HEAD]
        ]
        rows.append(("gap", f"... (+{omit_count})"))
        rows.extend(("word", w) for w in stem[-MATCH_PREVIEW_TAIL:])
        return rows

    def match_state(self) -> Literal["none", "many", "one", "exact"]:
        """Classify the current match situation.

        * ``"exact"`` - the typed text *is* a BIP39 word.
        * ``"one"``   - exactly one match (which differs from typed text).
        * ``"many"``  - 2+ matches.
        * ``"none"``  - zero matches: the prefix is not a valid stem.
        """
        text = self.typed_text()
        if text in _BIP39_WORD_SET:
            return "exact"
        stem = self.stem_matches()
        if not stem:
            return "none"
        if len(stem) == 1:
            return "one"
        return "many"

    # -- rendering -----------------------------------------------------

    def draw(self, fb: FrameBuffer) -> None:
        if self.pick_mode:
            self._draw_pick_mode(fb)
            return
        self._draw_type_mode(fb)

    def _draw_pick_mode(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        fb.draw.rectangle((0, 0, DISPLAY_WIDTH, 26), fill=(20, 20, 32))
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            13,
            self.title,
            size=14,
            color=COLOR_ACCENT,
            anchor="mm",
        )

        typed = self.typed_text()
        stem_label = typed[:22] + ("..." if len(typed) > 22 else "")
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            41,
            f"Stem: {stem_label}",
            size=11,
            color=COLOR_DIM,
            anchor="mm",
        )
        matches = self.stem_matches()
        if not matches:
            self.pick_mode = False
            self._draw_type_mode(fb)
            return

        self.pick_index %= len(matches)
        first = self._pick_first_visible()

        py_base = 60
        row_h = 22
        visible = matches[first : first + PICK_VISIBLE_LINES]
        for row, word in enumerate(visible):
            gi = first + row
            is_hi = gi == self.pick_index
            ry_mid = py_base + row * row_h
            ry0 = ry_mid - row_h // 2 + 2
            ry1 = ry_mid + row_h // 2 + 2
            if is_hi:
                fb.draw.rectangle((4, ry0, DISPLAY_WIDTH - 4, ry1), fill=(44, 60, 90))
                col = COLOR_FG
            else:
                col = COLOR_DIM if len(word) > 17 else COLOR_FG
            draw_text(fb, 12, ry_mid, word[:24], size=13, color=col, anchor="lm")

        if len(matches) > PICK_VISIBLE_LINES:
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                DISPLAY_HEIGHT - 54,
                f"{len(matches)} matches  {self.pick_index + 1}/{len(matches)}",
                size=10,
                color=COLOR_DIM,
                anchor="mm",
            )

        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 12,
            "UP/DWN pick   A select   B back",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )

    def _draw_type_mode(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        # Title bar
        fb.draw.rectangle((0, 0, DISPLAY_WIDTH, 26), fill=(20, 20, 32))
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            13,
            self.title,
            size=14,
            color=COLOR_ACCENT,
            anchor="mm",
        )

        stem = self.stem_matches()
        state = self.match_state()

        # Prefix + candidate, big, centered horizontally (bbox-based so the
        # highlight box doesn't cover adjacent prefix letters — the bitmap
        # font widths are nowhere near fixed 8px per char.)
        fz = _MAIN_ENTRY_FONT
        cand_color = {
            "exact": COLOR_OK,
            "one": COLOR_OK,
            "many": COLOR_ACCENT,
            "none": COLOR_DANGER,
        }[state]

        prefix_text = self.prefix
        suffix_text = "".join(self.letters[self.cursor + 1 :])
        gap_px = 6
        pad_x, pad_y = 6, 4
        cand_bb = text_bbox(self.candidate, size=fz)
        cand_px_h = cand_bb[3] - cand_bb[1]
        cand_box_w = max(cand_bb[2] - cand_bb[0], 8) + 2 * pad_x
        cand_box_h = max(cand_px_h + 2 * pad_y, 28)

        prefix_px_w = 0
        if prefix_text:
            pb = text_bbox(prefix_text, size=fz)
            prefix_px_w = pb[2] - pb[0]

        suffix_px_w = 0
        if suffix_text:
            sb = text_bbox(suffix_text, size=fz)
            suffix_px_w = sb[2] - sb[0]

        gutter_before = gap_px if prefix_text else 0
        gutter_after = gap_px if suffix_text else 0
        cluster_w = prefix_px_w + gutter_before + cand_box_w + gutter_after + suffix_px_w
        start_x = max(4, (DISPLAY_WIDTH - cluster_w) // 2)
        text_y = 52

        x = start_x
        if prefix_text:
            draw_text(
                fb,
                x,
                text_y,
                prefix_text,
                size=fz,
                color=COLOR_FG,
                anchor="lm",
            )
            x += prefix_px_w + gutter_before

        cand_left = x
        cand_top = text_y - cand_box_h // 2
        cand_right = cand_left + cand_box_w
        cand_bottom = cand_top + cand_box_h
        fb.draw.rectangle(
            (cand_left, cand_top, cand_right, cand_bottom),
            outline=cand_color,
            width=2,
            fill=(28, 32, 48),
        )
        cx = cand_left + cand_box_w // 2
        draw_text(
            fb,
            cx,
            text_y,
            self.candidate,
            size=fz,
            color=cand_color,
            anchor="mm",
        )
        if suffix_text:
            draw_text(
                fb,
                cand_right + gutter_after,
                text_y,
                suffix_text,
                size=fz,
                color=COLOR_FG,
                anchor="lm",
            )

        # Match counter / state message (lazily so we don't index an
        # empty match list).
        if state == "exact":
            state_msg = f"OK: {self.typed_text()!r}"
        elif state == "one":
            state_msg = f"-> {stem[0]}"
        elif state == "many":
            state_msg = f"{len(stem)} matches"
        else:
            state_msg = "no match"
        state_color = cand_color
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            82,
            state_msg,
            size=11,
            color=state_color,
            anchor="mm",
        )

        preview = self.match_preview_rows()
        y = 104
        first_word_highlighted = False
        for kind, txt in preview:
            if kind == "gap":
                draw_text(
                    fb,
                    DISPLAY_WIDTH // 2,
                    y,
                    txt,
                    size=10,
                    color=COLOR_DIM,
                    anchor="mm",
                )
            else:
                highlight = (
                    not first_word_highlighted and state in ("one", "many")
                )
                first_word_highlighted = True
                color = COLOR_ACCENT if highlight else COLOR_FG
                draw_text(fb, DISPLAY_WIDTH // 2, y, txt, size=12, color=color, anchor="mm")
            y += 14
            if y > DISPLAY_HEIGHT - 38:
                break

        # Footer hints (two lines)
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 26,
            "UP/DWN letter   L back   R next",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
        if state == "many":
            footer2 = "A pick   B del   hold B cancel"
        elif state in ("one", "exact"):
            footer2 = "A select   B del   hold B cancel"
        else:
            footer2 = "B del   hold B cancel"
        if self.show_hold_left_prev_hint:
            footer2 += "   L prev word"
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 12,
            footer2,
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )


# Higher-level multi-word mnemonic entry follows.


MnemonicEntryMode = Literal["restore", "create-confirm"]
MnemonicPhase = Literal["entry", "review", "edit"]


@dataclass
class MnemonicEntryScreen:
    """Drive the user through a 12- or 24-word BIP39 phrase.

    Two modes:

    * ``"restore"``         — user types each word; after the last word a
                              **review** screen lists every word with a
                              ✓/✗ checksum banner. From there they may edit
                              any slot or confirm when valid. **L** on the
                              first letter (or hold **L**) backs up one word.
    * ``"create-confirm"``  — Pi generated the phrase and showed it to the
                              user; user re-types each word; the screen
                              compares each entry against the expected
                              word and surfaces any mismatch before
                              continuing. The expected words are NEVER
                              echoed.

    On success ``result`` is the space-separated mnemonic. On user
    cancel (long B during entry/review/edit word screen) or on a
    confirmed mismatch (create-confirm mode) ``result`` is ``None``.
    """

    word_count: int = 12
    mode: MnemonicEntryMode = "restore"
    expected: list[str] | None = None
    done: bool = False
    result: str | None = None
    error: str | None = None  # populated when create-confirm sees a mismatch
    words: list[str] = field(default_factory=list)
    current: WordEntryScreen = field(init=False)
    phase: MnemonicPhase = "entry"
    review_view: ListView | None = None
    review_cursor: int = 0
    edit_index: int | None = None

    def __post_init__(self) -> None:
        if self.word_count not in (12, 24):
            raise ValueError("word_count must be 12 or 24")
        if self.mode == "create-confirm":
            if self.expected is None or len(self.expected) != self.word_count:
                raise ValueError(
                    "create-confirm mode requires `expected` with len == word_count"
                )
            for w in self.expected:
                if w not in _BIP39_WORD_SET:
                    raise ValueError(f"expected mnemonic contains non-BIP39 word: {w!r}")
        self.current = self._new_word_screen()

    def mnemonic_checksum_ok(self) -> bool:
        """True iff accumulated ``words`` form a valid BIP39 mnemonic."""
        from piwallet.core.mnemonic import MnemonicError, validate

        if len(self.words) != self.word_count:
            return False
        try:
            validate(" ".join(self.words))
            return True
        except MnemonicError:
            return False

    def _new_word_screen(self) -> WordEntryScreen:
        n = len(self.words) + 1
        w = WordEntryScreen(
            title=f"Word {n} of {self.word_count}",
            expected_position=n if self.mode == "create-confirm" else None,
        )
        w.show_hold_left_prev_hint = len(self.words) > 0
        return w

    # -- driver --------------------------------------------------------

    def _maybe_go_previous_word(self, event: Event) -> bool:
        """True when the operator wants to re-edit the prior word slot."""
        if not self.words or event.button != Button.LEFT:
            return False
        if event.kind == EventKind.LONG:
            return True
        if event.kind == EventKind.PRESS:
            return not self.current.pick_mode and self.current.cursor == 0
        return False

    def _go_to_previous_word(self) -> None:
        prev_word = self.words.pop()
        n = len(self.words) + 1
        w = WordEntryScreen(
            title=f"Word {n} of {self.word_count}",
            letters=list(prev_word),
            cursor=max(0, len(prev_word) - 1),
            expected_position=n if self.mode == "create-confirm" else None,
        )
        w.show_hold_left_prev_hint = len(self.words) > 0
        self.current = w

    def _enter_review(self) -> None:
        self.phase = "review"
        self._build_review_view()

    def _build_review_view(self) -> None:
        ok = self.mnemonic_checksum_ok()
        title = "✓ Phrase OK" if ok else "✗ Checksum invalid"
        items = [
            ListItem(f"{i + 1:>2}. {w}", value=("edit", i))
            for i, w in enumerate(self.words)
        ]
        self.review_view = ListView(
            items=items,
            title=title,
            title_color=COLOR_OK if ok else COLOR_DANGER,
            cursor=min(self.review_cursor, len(items) - 1),
            visible_rows=6,
        )

    def _finalize_restore_success(self) -> None:
        phrase = " ".join(self.words)
        from piwallet.core.mnemonic import validate

        validate(phrase)
        self.done = True
        self.result = phrase
        self.error = None

    def _finalize_create_confirm_success(self) -> None:
        self.done = True
        self.result = " ".join(self.words)

    def _begin_edit_word(self, index: int) -> None:
        self.phase = "edit"
        self.edit_index = index
        self.current = WordEntryScreen(title=f"Word {index + 1} of {self.word_count}")
        self.current.show_hold_left_prev_hint = False

    def _return_to_review(self) -> None:
        self.phase = "review"
        self.edit_index = None
        self._build_review_view()

    def _review_on_event(self, event: Event) -> None:
        assert self.review_view is not None
        b = event.button
        k = event.kind

        if b == Button.B and k == EventKind.LONG:
            self.done = True
            self.result = None
            self.error = None
            return

        # A = confirm the wallet (when checksum is valid). Never edit.
        if b == Button.A and k == EventKind.PRESS:
            if self.mnemonic_checksum_ok():
                self._finalize_restore_success()
            return

        # RIGHT = edit the currently highlighted word.
        if b == Button.RIGHT and k == EventKind.PRESS:
            self.review_cursor = self.review_view.cursor
            payload = self.review_view.items[self.review_view.cursor].value
            if isinstance(payload, tuple) and payload[0] == "edit":
                self._begin_edit_word(payload[1])
            return

        # UP / DOWN scroll the list.
        self.review_view.on_event(event)
        # Drain any accidental `confirmed` the ListView may have set
        # (shouldn't happen now that A is intercepted above, but keep
        # as a safety net).
        self.review_view.confirmed = None

    def _edit_on_event(self, event: Event) -> None:
        self.current.on_event(event)
        if not self.current.done:
            return
        idx = self.edit_index
        if idx is None:
            self._return_to_review()
            return
        if self.current.result is not None:
            self.words[idx] = self.current.result
        self.edit_index = None
        self._return_to_review()

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        if self.phase == "review":
            self._review_on_event(event)
            return
        if self.phase == "edit":
            self._edit_on_event(event)
            return

        if self._maybe_go_previous_word(event):
            self._go_to_previous_word()
            return

        self.current.on_event(event)
        if not self.current.done:
            return
        if self.current.result is None:
            self.done = True
            self.result = None
            return
        word = self.current.result
        if self.mode == "create-confirm":
            assert self.expected is not None
            expected_word = self.expected[len(self.words)]
            if word != expected_word:
                self.done = True
                self.result = None
                self.error = (
                    f"word {len(self.words) + 1} mismatch: typed {word!r}, "
                    f"expected something else. Check your written copy."
                )
                return
        self.words.append(word)
        if len(self.words) == self.word_count:
            if self.mode == "restore":
                self._enter_review()
            else:
                self._finalize_create_confirm_success()
            return
        self.current = self._new_word_screen()

    def draw(self, fb: FrameBuffer) -> None:
        if self.phase == "review" and self.review_view is not None:
            self.review_view.draw(fb)
            ok = self.mnemonic_checksum_ok()
            hint = (
                "A save   R edit word   hold B cancel"
                if ok
                else "R edit word   hold B cancel"
            )
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                DISPLAY_HEIGHT - 11,
                hint,
                size=10,
                color=COLOR_OK if ok else COLOR_DANGER,
                anchor="mm",
            )
            return
        self.current.draw(fb)

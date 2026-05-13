"""Create-wallet confirmation: pick each memorized word from a random pool."""

from __future__ import annotations

import secrets

from piwallet.core.mnemonic import BIP39_WORDLIST
from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DANGER,
    COLOR_DIM,
    COLOR_FG,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    FrameBuffer,
)
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.widgets import draw_text

# Correct word plus this many distinct decoys (seven rows visible on-panel).
CONFIRM_POOL_SIZE: int = 7

RNG = secrets.SystemRandom()

VISIBLE_POOL_ROWS: int = 7


class MnemonicConfirmPickScreen:
    """Shuffle a pool containing the next expected word — no letter typing."""

    phrase_words: tuple[str, ...]
    index: int
    pool: list[str]
    cursor: int
    scroll: int
    wrong_notice: bool
    done: bool
    result: str | None

    def __init__(self, phrase_words: list[str]) -> None:
        if len(phrase_words) not in (12, 24):
            raise ValueError("phrase must have 12 or 24 words")
        wordset = frozenset(BIP39_WORDLIST)
        if not all(w in wordset for w in phrase_words):
            raise ValueError("every word must be valid BIP39 English")
        self.phrase_words = tuple(phrase_words)
        self.index = 0
        self.pool = []
        self.cursor = 0
        self.scroll = 0
        self.wrong_notice = False
        self.done = False
        self.result = None
        self._new_pool()

    def _target(self) -> str:
        return self.phrase_words[self.index]

    def _new_pool(self) -> None:
        target = self._target()
        distractors_all = [w for w in BIP39_WORDLIST if w != target]
        n_decoys = CONFIRM_POOL_SIZE - 1
        decoys = RNG.sample(distractors_all, n_decoys)
        pool_list = [*decoys, target]
        RNG.shuffle(pool_list)
        self.pool = pool_list
        self.cursor = RNG.randrange(len(pool_list))
        self.scroll = 0
        self._clamp_scroll()

    def _clamp_scroll(self) -> None:
        if not self.pool:
            self.scroll = 0
            return
        mx = max(0, len(self.pool) - VISIBLE_POOL_ROWS)
        self.scroll = max(0, min(self.scroll, mx))
        if self.cursor < self.scroll:
            self.scroll = self.cursor
        if self.cursor >= self.scroll + VISIBLE_POOL_ROWS:
            self.scroll = self.cursor - VISIBLE_POOL_ROWS + 1

    def _advance_or_finish(self) -> None:
        self.index += 1
        if self.index >= len(self.phrase_words):
            self.done = True
            self.result = " ".join(self.phrase_words)
            self.pool = []
        else:
            self._new_pool()
            self.wrong_notice = False

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        pool = self.pool
        b = event.button
        k = event.kind
        if b == Button.B and k == EventKind.LONG:
            self.done = True
            self.result = None
            return
        if b in (Button.UP, Button.LEFT) and k in (EventKind.PRESS, EventKind.REPEAT):
            self.cursor = len(pool) - 1 if self.cursor == 0 else self.cursor - 1
            self.wrong_notice = False
            self._clamp_scroll()
            return
        if b in (Button.DOWN, Button.RIGHT) and k in (
            EventKind.PRESS,
            EventKind.REPEAT,
        ):
            self.cursor = 0 if self.cursor >= len(pool) - 1 else self.cursor + 1
            self.wrong_notice = False
            self._clamp_scroll()
            return
        if b == Button.B and k == EventKind.PRESS:
            self.wrong_notice = False
            return
        if b in (Button.A, Button.SELECT) and k == EventKind.PRESS:
            choice = pool[self.cursor]
            if choice != self._target():
                self.wrong_notice = True
                return
            self._advance_or_finish()

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        fb.draw.rectangle((0, 0, DISPLAY_WIDTH, 28), fill=(20, 20, 32))
        n_words = len(self.phrase_words)
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            13,
            f"Confirm {self.index + 1}/{n_words}",
            size=14,
            color=COLOR_ACCENT,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            41,
            "Pick matching word:",
            size=11,
            color=COLOR_DIM,
            anchor="mm",
        )

        pool = self.pool
        self._clamp_scroll()
        py_base = 58
        row_h = 24
        for row in range(VISIBLE_POOL_ROWS):
            wi = self.scroll + row
            if wi >= len(pool):
                break
            word = pool[wi]
            is_cur = wi == self.cursor
            ry_mid = py_base + row * row_h
            ry0 = ry_mid - row_h // 2
            ry1 = ry_mid + row_h // 2
            if is_cur:
                fb.draw.rectangle((4, ry0, DISPLAY_WIDTH - 4, ry1), fill=(44, 60, 90))
                col = COLOR_FG
            else:
                col = COLOR_DIM if len(word) > 17 else COLOR_FG
            draw_text(fb, 10, ry_mid, word[:22], size=13, color=col, anchor="lm")

        if len(pool) > VISIBLE_POOL_ROWS:
            track_y0 = py_base - 14
            track_y1 = DISPLAY_HEIGHT - 64
            track_h = max(20, track_y1 - track_y0)
            fb.draw.rectangle(
                (DISPLAY_WIDTH - 4, track_y0, DISPLAY_WIDTH - 2, track_y0 + track_h),
                fill=(42, 42, 52),
            )
            denom = len(pool) - VISIBLE_POOL_ROWS
            thy = (
                track_h * min(self.scroll, denom) // max(1, denom)
                if denom
                else 0
            )
            thumb_h = max(14, track_h * VISIBLE_POOL_ROWS // len(pool))
            fb.draw.rectangle(
                (
                    DISPLAY_WIDTH - 4,
                    track_y0 + thy,
                    DISPLAY_WIDTH - 2,
                    track_y0 + thy + thumb_h,
                ),
                fill=COLOR_ACCENT,
            )

        if self.wrong_notice:
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                DISPLAY_HEIGHT - 46,
                "Wrong word.",
                size=11,
                color=COLOR_DANGER,
                anchor="mm",
            )

        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 26,
            "LR/UD cycle   A pick",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 12,
            "hold B bail",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )

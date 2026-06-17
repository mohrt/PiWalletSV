"""Bonnet screens for capturing physical entropy (camera, dice)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from io import BytesIO

from PIL import Image, ImageOps

from piwallet.bonnet.camera_still import capture_still_jpeg_bytes
from piwallet.bonnet.entropy_camera import EntropyDualStreamCamera
from piwallet.core.mnemonic import MIN_DICE_ROLLS
from piwallet.camera_lcd import paste_cover, rgb888_thumbnail
from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DIM,
    COLOR_FG,
    COLOR_OK,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    FrameBuffer,
)
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.widgets import draw_text

log = logging.getLogger(__name__)

_TITLE_H: int = 26
_FOOTER_RESERVE: int = 40
_PREVIEW_TOP: int = _TITLE_H + 2
_PREVIEW_BOTTOM: int = DISPLAY_HEIGHT - _FOOTER_RESERVE


@dataclass
class CameraEntropyScreen:
    """Low-FPS live preview on the TFT; A captures a full main-stream JPEG for entropy."""

    title: str = "Photo entropy"
    done: bool = False
    result: bytes | None = None
    error: str | None = None
    busy: bool = False
    preview_interval_s: float = 0.25
    preview_thumb_max_edge: int = 200
    clock_s: Callable[[], float] = field(default_factory=lambda: time.monotonic)
    camera_cls: type = EntropyDualStreamCamera
    _dual: EntropyDualStreamCamera | None = field(init=False, default=None)
    _dual_failed: bool = field(init=False, default=False)
    _dual_open_attempted: bool = field(init=False, default=False)
    _cached_thumb: Image.Image | None = field(init=False, default=None)
    _last_preview_mono: float = field(init=False, default=-1.0)

    def _close_dual(self) -> None:
        dual = self._dual
        if dual is None:
            return
        self._dual = None
        try:
            dual.close()
        except Exception:
            log.exception("camera close after entropy screen")

    def _try_open_dual(self) -> None:
        if self._dual_open_attempted or self._dual is not None or self._dual_failed:
            return
        self._dual_open_attempted = True
        try:
            cam = self.camera_cls()
            cam.open()
            self._dual = cam
        except Exception:
            log.exception("entropy camera open failed; falling back to still-only capture")
            self._dual_failed = True
            self._dual = None

    def _refresh_preview_thumb(self) -> None:
        if self._dual is None or self.busy:
            return
        now = self.clock_s()
        too_soon = (
            self._last_preview_mono >= 0
            and (now - self._last_preview_mono) < self.preview_interval_s
        )
        if too_soon:
            return
        self._last_preview_mono = now
        try:
            arr = self._dual.read_preview_rgb()
            self._cached_thumb = rgb888_thumbnail(arr, max_edge=self.preview_thumb_max_edge)
        except Exception as exc:
            log.debug("lores preview frame failed: %s", exc)

    def on_event(self, event: Event) -> None:
        if self.done or self.busy:
            return
        if event.button == Button.B and event.kind in (EventKind.PRESS, EventKind.LONG):
            self._close_dual()
            self.done = True
            self.result = None
            self.error = None
            return
        if event.button == Button.A and event.kind == EventKind.PRESS:
            self.busy = True
            try:
                if self._dual is not None:
                    jpeg = self._dual.capture_entropy_jpeg()
                else:
                    jpeg = capture_still_jpeg_bytes()
                self.result = jpeg
                self.error = None
                self.done = True
            except Exception as exc:
                log.exception("camera capture failed")
                if isinstance(exc, IndexError):
                    self.error = (
                        "Camera unavailable (no sensor). "
                        "Try Random entropy or restart bonnet."
                    )
                else:
                    self.error = str(exc)
            else:
                self._close_dual()
            finally:
                self.busy = False

    def draw(self, fb: FrameBuffer) -> None:
        if not self.done and not self._dual_failed:
            self._try_open_dual()
            self._refresh_preview_thumb()

        fb.clear(COLOR_BG)
        fb.draw.rectangle((0, 0, DISPLAY_WIDTH, _TITLE_H), fill=(20, 20, 32))
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            _TITLE_H // 2,
            self.title,
            size=14,
            color=COLOR_ACCENT,
            anchor="mm",
        )

        box = (0, _PREVIEW_TOP, DISPLAY_WIDTH, _PREVIEW_BOTTOM)
        if self._cached_thumb is not None and not self.busy:
            paste_cover(fb.image, self._cached_thumb, box)
        else:
            fb.draw.rectangle(box, fill=(12, 12, 18))

        if self.busy:
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                (_PREVIEW_TOP + _PREVIEW_BOTTOM) // 2,
                "Capturing...",
                size=12,
                color=COLOR_FG,
                anchor="mm",
            )
        elif self._dual_failed and self._cached_thumb is None:
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                (_PREVIEW_TOP + _PREVIEW_BOTTOM) // 2 - 8,
                "Preview unavailable",
                size=11,
                color=COLOR_DIM,
                anchor="mm",
            )
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                (_PREVIEW_TOP + _PREVIEW_BOTTOM) // 2 + 10,
                "Still captures on A",
                size=10,
                color=COLOR_DIM,
                anchor="mm",
            )

        if self.error:
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                _PREVIEW_BOTTOM + 4,
                self.error[:88],
                size=9,
                color=(240, 80, 70),
                anchor="mm",
            )

        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 28,
            "A capture   B cancel",
            size=11,
            color=COLOR_DIM,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 12,
            "Preview = aim   JPEG = entropy",
            size=9,
            color=COLOR_OK,
            anchor="mm",
        )


def _jpeg_preview_thumb(jpeg: bytes, *, max_edge: int = 200) -> Image.Image:
    """Decode a captured entropy JPEG for the TFT confirmation screen."""
    img = Image.open(BytesIO(jpeg)).convert("RGB")
    return ImageOps.contain(img, (max_edge, max_edge), Image.Resampling.BILINEAR)


@dataclass
class CameraEntropyConfirmScreen:
    """Show the captured still and wait for operator acknowledgement."""

    jpeg: bytes
    title: str = "Photo captured"
    done: bool = False
    confirmed: bool | None = None
    preview_thumb_max_edge: int = 200
    _thumb: Image.Image = field(init=False)

    def __post_init__(self) -> None:
        self._thumb = _jpeg_preview_thumb(
            self.jpeg, max_edge=self.preview_thumb_max_edge
        )

    def _size_label(self) -> str:
        n = len(self.jpeg)
        if n >= 1024:
            return f"{n // 1024} KB saved"
        return f"{n} B saved"

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        if event.button == Button.B and event.kind in (EventKind.PRESS, EventKind.LONG):
            self.done = True
            self.confirmed = None
            return
        if event.button == Button.A and event.kind == EventKind.PRESS:
            self.done = True
            self.confirmed = True

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        fb.draw.rectangle((0, 0, DISPLAY_WIDTH, _TITLE_H), fill=(20, 20, 32))
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            _TITLE_H // 2,
            self.title,
            size=14,
            color=COLOR_OK,
            anchor="mm",
        )

        box = (0, _PREVIEW_TOP, DISPLAY_WIDTH, _PREVIEW_BOTTOM)
        paste_cover(fb.image, self._thumb, box)

        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            _PREVIEW_BOTTOM + 6,
            self._size_label(),
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )

        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 28,
            "A continue   B retake",
            size=11,
            color=COLOR_DIM,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 12,
            "Mixed with OS random bytes",
            size=9,
            color=COLOR_OK,
            anchor="mm",
        )


@dataclass
class DiceEntropyScreen:
    """Record many consecutive 6-sided die readings."""

    word_count: int = 12
    done: bool = False
    result: list[int] | None = None
    rolls: list[int] = field(default_factory=list)
    current_face: int = 3

    def __post_init__(self) -> None:
        self._req = MIN_DICE_ROLLS[self.word_count]

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        b = event.button
        k = event.kind
        if b == Button.B and k in (EventKind.PRESS, EventKind.LONG):
            self.done = True
            self.result = None
            return
        if b == Button.UP and k in (EventKind.PRESS, EventKind.REPEAT):
            self.current_face = 1 if self.current_face == 6 else self.current_face + 1
        elif b == Button.DOWN and k in (EventKind.PRESS, EventKind.REPEAT):
            self.current_face = 6 if self.current_face == 1 else self.current_face - 1
        elif b == Button.LEFT and k in (EventKind.PRESS, EventKind.REPEAT):
            if self.rolls:
                self.rolls.pop()
        elif b == Button.A and k == EventKind.PRESS:
            self.rolls.append(self.current_face)
            if len(self.rolls) >= self._req:
                self.done = True
                self.result = list(self.rolls)

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        fb.draw.rectangle((0, 0, DISPLAY_WIDTH, 26), fill=(20, 20, 32))
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            13,
            "Dice entropy",
            size=14,
            color=COLOR_ACCENT,
            anchor="mm",
        )
        n = len(self.rolls)
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            46,
            f"Roll {n} / {self._req}",
            size=13,
            color=COLOR_FG,
            anchor="mm",
        )
        draw_text(fb, DISPLAY_WIDTH // 2, 66, "face UP/DWN", size=11, color=COLOR_DIM, anchor="mm")
        sz = 58
        x0 = (DISPLAY_WIDTH - sz) // 2
        y0 = 78
        fb.draw.rectangle(
            (x0, y0, x0 + sz, y0 + sz),
            outline=COLOR_ACCENT,
            width=3,
            fill=(24, 28, 40),
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            y0 + sz // 2 + 2,
            str(self.current_face),
            size=36,
            color=COLOR_OK,
            anchor="mm",
        )

        tail = "".join(str(d) for d in self.rolls[-26:])
        draw_text(fb, 8, DISPLAY_HEIGHT - 58, tail or "-", size=9, color=COLOR_DIM, anchor="la")

        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 26,
            "A roll   L undo",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 12,
            "B cancel",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )

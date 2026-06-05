"""Hardware test screens reachable from the diagnostics menu."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Literal

from piwallet.bonnet.camera_preview import CameraPreviewState
from piwallet.camera_lcd import paste_cover
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

HwTestResult = Literal["back"]

_TITLE_H = 22
_PREVIEW_TOP = _TITLE_H + 2
_PREVIEW_BOTTOM = DISPLAY_HEIGHT - 28


class ScreenPattern(Enum):
    GRID = "grid"
    RED = "red"
    GREEN = "green"
    BLUE = "blue"
    WHITE = "white"
    CHECKER = "checker"


_SCREEN_PATTERNS: tuple[ScreenPattern, ...] = tuple(ScreenPattern)


def _button_label(button: Button) -> str:
    return {
        Button.UP: "UP",
        Button.DOWN: "DOWN",
        Button.LEFT: "LEFT",
        Button.RIGHT: "RIGHT",
        Button.SELECT: "JOY",
        Button.A: "A",
        Button.B: "B",
    }[button]


@dataclass
class _InputTracker:
    down: set[Button] = field(default_factory=set)
    last_line: str = "press controls…"

    def on_event(self, event: Event) -> None:
        if event.kind == EventKind.PRESS:
            self.down.add(event.button)
            self.last_line = f"{_button_label(event.button)} pressed"
        elif event.kind == EventKind.RELEASE:
            self.down.discard(event.button)
            self.last_line = "press controls…"


def _finish_on_back(
    screen: object,
    event: Event,
    *,
    allow_a: bool = False,
    long_b_only: bool = False,
) -> bool:
    b = event.button
    k = event.kind
    if b == Button.B:
        if long_b_only:
            if k == EventKind.LONG:
                screen.done = True  # type: ignore[attr-defined]
                screen.result = "back"  # type: ignore[attr-defined]
                return True
            return False
        if k == EventKind.PRESS:
            screen.done = True  # type: ignore[attr-defined]
            screen.result = "back"  # type: ignore[attr-defined]
            return True
    if allow_a and b == Button.A and k == EventKind.PRESS:
        screen.done = True  # type: ignore[attr-defined]
        screen.result = "back"  # type: ignore[attr-defined]
        return True
    return False


@dataclass
class JoystickTestScreen:
    done: bool = False
    result: HwTestResult | None = None
    _tracker: _InputTracker = field(default_factory=_InputTracker)

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        if _finish_on_back(self, event, allow_a=False):
            return
        self._tracker.on_event(event)

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        _draw_title(fb, "Joystick")
        cx, cy = DISPLAY_WIDTH // 2, DISPLAY_HEIGHT // 2 - 8
        _draw_arrow(fb, cx, cy - 44, "UP", Button.UP in self._tracker.down)
        _draw_arrow(fb, cx, cy + 44, "DN", Button.DOWN in self._tracker.down)
        _draw_arrow(fb, cx - 44, cy, "LT", Button.LEFT in self._tracker.down)
        _draw_arrow(fb, cx + 44, cy, "RT", Button.RIGHT in self._tracker.down)
        joy_on = Button.SELECT in self._tracker.down
        fill = COLOR_ACCENT if joy_on else (32, 38, 52)
        outline = COLOR_OK if joy_on else COLOR_DIM
        r = 16
        fb.draw.ellipse(
            (cx - r, cy - r, cx + r, cy + r),
            fill=fill,
            outline=outline,
            width=2,
        )
        draw_text(fb, cx, cy, "JOY", size=9, color=COLOR_FG, anchor="mm")
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 24,
            self._tracker.last_line,
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
        _draw_footer(fb, hint="B: back")


@dataclass
class ButtonsTestScreen:
    done: bool = False
    result: HwTestResult | None = None
    _tracker: _InputTracker = field(default_factory=_InputTracker)

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        if _finish_on_back(self, event, allow_a=False, long_b_only=True):
            return
        if event.button in (Button.A, Button.B):
            self._tracker.on_event(event)

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        _draw_title(fb, "Buttons")
        cy = DISPLAY_HEIGHT // 2 - 6
        _draw_button_pad(fb, 62, cy, "A", Button.A in self._tracker.down)
        _draw_button_pad(fb, DISPLAY_WIDTH - 62, cy, "B", Button.B in self._tracker.down)
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 24,
            self._tracker.last_line,
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
        _draw_footer(fb, hint="hold B: back")


@dataclass
class ScreenTestScreen:
    done: bool = False
    result: HwTestResult | None = None
    pattern_index: int = 0

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        if _finish_on_back(self, event, allow_a=True):
            return
        if event.kind not in (EventKind.PRESS, EventKind.REPEAT):
            return
        if event.button == Button.RIGHT:
            self.pattern_index = (self.pattern_index + 1) % len(_SCREEN_PATTERNS)
        elif event.button == Button.LEFT:
            self.pattern_index = (self.pattern_index - 1) % len(_SCREEN_PATTERNS)

    def draw(self, fb: FrameBuffer) -> None:
        pattern = _SCREEN_PATTERNS[self.pattern_index]
        _paint_pattern(fb, pattern)
        _draw_title(fb, f"Screen: {pattern.value}")
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 24,
            "L/R pattern",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
        _draw_footer(fb, hint="A/B: back")


@dataclass
class CameraTestScreen:
    state: CameraPreviewState = field(default_factory=CameraPreviewState)
    done: bool = False
    result: HwTestResult | None = None
    _started: bool = field(init=False, default=False)
    start_worker: Callable[[CameraPreviewState], None] | None = None

    def _ensure_started(self) -> None:
        if self._started:
            return
        self._started = True
        if self.start_worker is not None:
            self.start_worker(self.state)

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        if _finish_on_back(self, event, allow_a=True):
            with self.state.lock:
                self.state.cancel_requested = True
            return

    def draw(self, fb: FrameBuffer) -> None:
        self._ensure_started()
        with self.state.lock:
            thumb = self.state.latest_thumb
            error = self.state.error

        fb.clear(COLOR_BG)
        _draw_title(fb, "Camera")
        box = (8, _PREVIEW_TOP, DISPLAY_WIDTH - 8, _PREVIEW_BOTTOM)
        if error:
            fb.draw.rectangle(box, fill=(24, 16, 16))
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                (box[1] + box[3]) // 2,
                "Camera error",
                size=11,
                color=COLOR_FG,
                anchor="mm",
            )
            for i, line in enumerate(_wrap(error, 26)[:3]):
                draw_text(
                    fb,
                    DISPLAY_WIDTH // 2,
                    (box[1] + box[3]) // 2 + 14 + i * 12,
                    line,
                    size=9,
                    color=COLOR_DIM,
                    anchor="mm",
                )
        elif thumb is not None:
            paste_cover(fb.image, thumb, box)
        else:
            fb.draw.rectangle(box, fill=(16, 16, 24))
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                (box[1] + box[3]) // 2,
                "Starting…",
                size=11,
                color=COLOR_DIM,
                anchor="mm",
            )
        _draw_footer(fb, hint="A/B: back")


def _draw_title(fb: FrameBuffer, title: str) -> None:
    fb.draw.rectangle((0, 0, DISPLAY_WIDTH, _TITLE_H), fill=(20, 20, 32))
    draw_text(
        fb,
        DISPLAY_WIDTH // 2,
        _TITLE_H // 2,
        title,
        size=12,
        color=COLOR_ACCENT,
        anchor="mm",
    )


def _draw_footer(fb: FrameBuffer, *, hint: str = "B: back") -> None:
    draw_text(
        fb,
        DISPLAY_WIDTH // 2,
        DISPLAY_HEIGHT - 10,
        hint,
        size=10,
        color=COLOR_DIM,
        anchor="mm",
    )


def _draw_arrow(
    fb: FrameBuffer,
    x: int,
    y: int,
    label: str,
    active: bool,
) -> None:
    w, h = 34, 22
    fill = (48, 64, 96) if active else (16, 16, 24)
    outline = COLOR_ACCENT if active else COLOR_DIM
    fb.draw.rectangle(
        (x - w // 2, y - h // 2, x + w // 2, y + h // 2),
        fill=fill,
        outline=outline,
        width=2,
    )
    draw_text(fb, x, y, label, size=10, color=COLOR_FG, anchor="mm")


def _draw_button_pad(
    fb: FrameBuffer,
    x: int,
    y: int,
    label: str,
    active: bool,
) -> None:
    w, h = 56, 40
    fill = (48, 64, 96) if active else (16, 16, 24)
    outline = COLOR_ACCENT if active else COLOR_DIM
    fb.draw.rectangle(
        (x - w // 2, y - h // 2, x + w // 2, y + h // 2),
        fill=fill,
        outline=outline,
        width=2,
    )
    draw_text(fb, x, y, label, size=18, color=COLOR_FG, anchor="mm")


def _paint_pattern(fb: FrameBuffer, pattern: ScreenPattern) -> None:
    if pattern == ScreenPattern.RED:
        fb.clear((180, 32, 32))
        return
    if pattern == ScreenPattern.GREEN:
        fb.clear((32, 160, 64))
        return
    if pattern == ScreenPattern.BLUE:
        fb.clear((32, 64, 180))
        return
    if pattern == ScreenPattern.WHITE:
        fb.clear((220, 220, 220))
        return
    if pattern == ScreenPattern.CHECKER:
        fb.clear(COLOR_BG)
        step = 16
        for y in range(0, DISPLAY_HEIGHT, step):
            for x in range(0, DISPLAY_WIDTH, step):
                if ((x // step) + (y // step)) % 2 == 0:
                    fb.draw.rectangle((x, y, x + step, y + step), fill=(48, 48, 56))
        return
    fb.clear(COLOR_BG)
    for x in range(0, DISPLAY_WIDTH, 24):
        fb.draw.line((x, 0, x, DISPLAY_HEIGHT), fill=(48, 48, 56))
    for y in range(0, DISPLAY_HEIGHT, 24):
        fb.draw.line((0, y, DISPLAY_WIDTH, y), fill=(48, 48, 56))


def _wrap(text: str, max_chars: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = words[0]
    for word in words[1:]:
        if len(cur) + 1 + len(word) <= max_chars:
            cur = f"{cur} {word}"
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    return lines

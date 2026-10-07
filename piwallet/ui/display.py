"""Display backends and the framebuffer abstraction.

Design
------
A ``FrameBuffer`` is a PIL ``Image`` plus a paired ``ImageDraw`` cursor
that widgets paint into. Once the frame is fully drawn, the app calls
``Display.flip(framebuf)`` which pushes the pixels to the physical
(or virtual) screen *atomically*. There is no partial-frame rendering;
the SPI bus blasts the whole 240x240 RGB565 buffer per refresh, which
on a Pi Zero 2 W at 24-32 MHz comfortably exceeds ~25 fps — well above
what the bonnet UX needs (mostly static menus, a couple of progress
bars, and joystick-driven cursors).

Two backends are provided:

* :class:`HeadlessDisplay` — keeps the last frame in memory. Use in
  tests and on development machines that have no SPI bus. ``image``
  exposes the latest frame for pixel-level assertions.
* :class:`ST7789Display` — wraps Adafruit's
  ``adafruit_rgb_display.st7789`` driver. Imported lazily so the
  module is importable on macOS.

Both back ends present the same ``Display`` API.
"""

from __future__ import annotations

import contextlib
import logging
from abc import ABC, abstractmethod
from typing import Any

from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

DISPLAY_WIDTH: int = 240
DISPLAY_HEIGHT: int = 240

# Common colour aliases. PiWalletSV uses a deliberately tiny palette so
# the UI stays high-contrast on a 1.3" panel.
COLOR_BG = (0, 0, 0)
COLOR_FG = (240, 240, 240)
COLOR_DIM = (140, 140, 140)
COLOR_ACCENT = (60, 180, 250)
COLOR_DANGER = (240, 90, 70)
COLOR_OK = (90, 220, 130)


class FrameBuffer:
    """A 240x240 RGB image plus a bound ``ImageDraw`` context.

    Widgets receive a ``FrameBuffer`` and paint into ``.image`` via
    ``.draw``. They do **not** flush to the screen themselves; the app
    main loop is responsible for calling ``Display.flip(framebuf)``
    once per frame.
    """

    __slots__ = ("draw", "image")

    def __init__(
        self,
        width: int = DISPLAY_WIDTH,
        height: int = DISPLAY_HEIGHT,
        background: tuple[int, int, int] = COLOR_BG,
    ) -> None:
        self.image: Image.Image = Image.new("RGB", (width, height), background)
        self.draw: ImageDraw.ImageDraw = ImageDraw.Draw(self.image)

    def clear(self, color: tuple[int, int, int] = COLOR_BG) -> None:
        """Fill the framebuffer with ``color`` and reset the draw cursor."""
        self.draw.rectangle((0, 0, self.image.width, self.image.height), fill=color)

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size


#: Minimum software-brightness multiplier. Below this the panel becomes
#: practically unreadable; we clamp the user-visible setting so a slip of
#: the joystick can't black the screen.
MIN_BRIGHTNESS: float = 0.20

#: Maximum brightness; the no-op identity that skips dimming entirely.
MAX_BRIGHTNESS: float = 1.0


class Display(ABC):
    """Backend-agnostic display contract.

    Implementations promise that ``flip(framebuf)`` is an atomic push:
    after it returns, the user can safely mutate ``framebuf`` again
    without tearing the on-screen image.

    ``brightness`` is a software dimming multiplier in
    ``[MIN_BRIGHTNESS, MAX_BRIGHTNESS]``. The bonnet's hardware
    backlight is a digital MOSFET gate (no PWM channel on its GPIO),
    so true backlight dimming isn't available; instead, the active
    backend may multiply pixel intensities before the SPI push.
    The default value of 1.0 is a no-op and incurs zero cost.
    """

    width: int = DISPLAY_WIDTH
    height: int = DISPLAY_HEIGHT
    brightness: float = MAX_BRIGHTNESS

    @abstractmethod
    def flip(self, framebuf: FrameBuffer) -> None:
        """Push the current frame to the physical or virtual screen."""

    def set_backlight(self, on: bool) -> None:  # noqa: B027 (optional backlight)
        """Drive the panel backlight when supported (e.g. ST7789 bonnet); default no-op."""
        pass

    def set_brightness(self, level: float) -> None:
        """Set the software-dimming multiplier in ``[MIN_BRIGHTNESS, MAX_BRIGHTNESS]``.

        The base implementation just stores the clamped value;
        subclasses that support visible dimming (currently
        :class:`ST7789Display`) consult ``self.brightness`` in
        ``flip()``.
        """
        self.brightness = clamp_brightness(level)

    def recover(self) -> None:  # noqa: B027 (optional override; default no-op)
        """Called by the run loop after any button event.

        Real hardware subclasses may override this to re-assert the display
        state in case a GPIO button press capacitively perturbed the RST or
        DC lines and left the panel in sleep / display-off mode.
        """

    def close(self) -> None:  # noqa: B027 (optional override; default no-op by design)
        """Optional teardown hook. Default is a no-op."""

    def __enter__(self) -> Display:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def clamp_brightness(level: float) -> float:
    """Clamp ``level`` into ``[MIN_BRIGHTNESS, MAX_BRIGHTNESS]``."""
    if level != level:  # NaN guard
        return MAX_BRIGHTNESS
    return max(MIN_BRIGHTNESS, min(MAX_BRIGHTNESS, float(level)))


class HeadlessDisplay(Display):
    """In-memory display backend used by tests and dev workflows.

    The latest pushed frame is exposed via :attr:`image`, and a
    monotonic :attr:`flip_count` counter is incremented per flush so
    tests can assert *how many* frames a widget required.
    """

    def __init__(
        self,
        width: int = DISPLAY_WIDTH,
        height: int = DISPLAY_HEIGHT,
    ) -> None:
        self.width = width
        self.height = height
        self.image: Image.Image = Image.new("RGB", (width, height), COLOR_BG)
        self.flip_count: int = 0
        self.backlight_on: bool = True
        # Optional: keep a small ring of recent frames for test diffing.
        self._history: list[Image.Image] = []

    def set_backlight(self, on: bool) -> None:
        self.backlight_on = bool(on)

    def flip(self, framebuf: FrameBuffer) -> None:
        # HeadlessDisplay deliberately does NOT apply software dimming —
        # tests assert exact pixel values on `image`, and a brightness
        # multiplier would silently break those. The recorded brightness
        # remains observable via the inherited `brightness` attribute.
        if framebuf.size != (self.width, self.height):
            raise ValueError(
                f"framebuf size {framebuf.size} does not match display "
                f"{(self.width, self.height)}"
            )
        # Copy so the caller can keep mutating its FrameBuffer without
        # changing what we have on screen.
        self.image = framebuf.image.copy()
        self.flip_count += 1
        self._history.append(self.image)
        if len(self._history) > 8:
            self._history = self._history[-8:]

    def pixel_at(self, x: int, y: int) -> tuple[int, int, int]:
        return self.image.getpixel((x, y))  # type: ignore[return-value]

    def recent(self) -> list[Image.Image]:
        return list(self._history)


class ST7789Display(Display):
    """Real ST7789 240x240 display attached to the Adafruit bonnet.

    Pin map matches Adafruit product 4506 (1.3" 240x240 TFT + joystick
    bonnet for Raspberry Pi):

    * CS  -> ``board.CE0`` (SPI chip-select 0)
    * DC  -> ``board.D25``
    * RST -> ``board.D24`` (hardware reset; matches Adafruit's Pi demos).
    * BL  -> ``board.D26`` (backlight; gated through a MOSFET on the
             bonnet so it stays OFF unless the pin is driven HIGH)

    **Row offset.** The bonnet connects a **240 x 240 window** cropped from an
    ST7789-sized internal RAM arrangement. Writes must skip the invisible
    top rows with ``y_offset=80``. If ``y_offset`` is left at 0 you get a band
    of **random noise occupying roughly the top third** of the glass while the
    rest of the UI looks fine — identical symptom to a wrong pitft/kernel
    offset. See Adafruit Learn (4506 Python setup) and
    ``scripts/st7789_solid_fill_test.py`` in this repo.

    The constructor *lazily* imports the Adafruit stack so the rest of
    the module is importable on macOS for unit tests.
    """

    def __init__(
        self,
        spi_baudrate: int = 24_000_000,
        backlight_on: bool = True,
        rotation: int = 180,
        *,
        x_offset: int = 0,
        y_offset: int = 80,
        use_hw_reset_pin: bool = True,
    ) -> None:  # pragma: no cover
        try:
            import board  # type: ignore[import-not-found]
            import digitalio  # type: ignore[import-not-found]
            from adafruit_rgb_display import st7789  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "ST7789Display requires the 'display' extra. "
                "Install with `bash scripts/bootstrap-pi-dev.sh` or "
                "`bash scripts/install-piwallet-deps.sh` on a Raspberry Pi."
            ) from exc

        if rotation not in (0, 90, 180, 270):
            raise ValueError(f"rotation must be one of 0/90/180/270, got {rotation}")
        self._rotation = rotation

        cs = digitalio.DigitalInOut(board.CE0)
        dc = digitalio.DigitalInOut(board.D25)
        rst_pin: Any = None
        if use_hw_reset_pin:
            try:
                rst_pin = digitalio.DigitalInOut(board.D24)
            except Exception:
                rst_pin = None
        self._device: Any = st7789.ST7789(
            board.SPI(),
            cs=cs,
            dc=dc,
            rst=rst_pin,
            baudrate=spi_baudrate,
            width=DISPLAY_WIDTH,
            height=DISPLAY_HEIGHT,
            x_offset=x_offset,
            y_offset=y_offset,
            rotation=rotation,
        )
        # The 1.3" 240x240 bonnet's backlight is gated through a MOSFET
        # on BCM 26. Without driving it HIGH the panel is being written
        # correctly but the LED is dark, so the screen looks blank.
        try:
            self._backlight: Any | None = digitalio.DigitalInOut(board.D26)
            self._backlight.switch_to_output(value=bool(backlight_on))
        except Exception:
            # Some bonnet revisions / overlays may already claim D26;
            # keep going so the SPI half still works for debugging.
            self._backlight = None

    def set_backlight(self, on: bool) -> None:  # pragma: no cover
        """Turn the backlight on/off without re-initialising the panel."""
        if self._backlight is not None:
            self._backlight.value = bool(on)

    def recover(self) -> None:  # pragma: no cover
        """Restore the display after an accidental hardware reset.

        Pressing the RIGHT joystick (GPIO D23 / physical pin 16) can
        capacitively couple to the RST line (GPIO D24 / physical pin 18)
        and trigger a brief hardware reset.

        Key constraint from the ST7789 datasheet: after SLPOUT (0x11) the
        **frame memory is locked for 120 ms**.  Any RAMWR that arrives during
        that window is silently ignored, so the flip() that follows must wait
        until the 120 ms has elapsed.  We put the sleep *inside* recover() so
        by the time run_screen calls flip() the panel is ready.
        """
        import time as _time

        try:
            self._device.write(0x11)       # SLPOUT — exits sleep / re-init power
            _time.sleep(0.120)             # ST7789: GRAM locked for 120 ms after SLPOUT
            self._device.write(0x3A, bytes([0x55]))  # COLMOD 16-bit colour
            self._device.write(0x36, bytes([0xC0]))  # MADCTL rotation=180 RGB
            self._device.write(0x13)       # NORON  normal display mode
            self._device.write(0x29)       # DISPON turn panel on
        except Exception as exc:  # pragma: no cover
            logger.warning("ST7789 recover() failed: %s", exc)

    def flip(self, framebuf: FrameBuffer) -> None:  # pragma: no cover
        img = framebuf.image
        if self.brightness < MAX_BRIGHTNESS:
            from PIL import ImageEnhance

            img = ImageEnhance.Brightness(img).enhance(self.brightness)
        self._device.image(img)

    def close(self) -> None:
        # pragma: no cover - hardware teardown only runs on the Pi.
        if self._backlight is None:
            return
        with contextlib.suppress(Exception):
            self._backlight.value = False


def rgb_to_fb_bytes(image: Image.Image, bits_per_pixel: int) -> bytes:
    """Pack an RGB image for a Linux framebuffer.

    16-bit panels (the Waveshare SPI HAT) want RGB565. 32-bit panels
    want BGRX, which is what the Pi's framebuffer usually uses.
    """
    if image.mode != "RGB":
        image = image.convert("RGB")
    raw = image.tobytes("raw", "RGB")
    if bits_per_pixel == 16:
        return _rgb565_le(raw)
    if bits_per_pixel == 32:
        return _bgra32(raw)
    raise ValueError(f"unsupported framebuffer depth: {bits_per_pixel}")


def _rgb565_le(raw: bytes) -> bytes:
    """RGB888 bytes to little-endian RGB565. One pass, no Python per pixel."""
    import numpy as np

    rgb = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
    r = rgb[:, 0].astype(np.uint16)
    g = rgb[:, 1].astype(np.uint16)
    b = rgb[:, 2].astype(np.uint16)
    pixel = ((r & np.uint16(0xF8)) << np.uint16(8)) | ((g & np.uint16(0xFC)) << np.uint16(3)) | (
        b >> np.uint16(3)
    )
    return pixel.astype("<u2").tobytes()


def _bgra32(raw: bytes) -> bytes:
    import numpy as np

    rgb = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
    out = np.empty((rgb.shape[0], 4), dtype=np.uint8)
    out[:, 0] = rgb[:, 2]
    out[:, 1] = rgb[:, 1]
    out[:, 2] = rgb[:, 0]
    out[:, 3] = 255
    return out.tobytes()


# linux/kd.h — switch the VT off text mode so fbcon stops drawing its cursor
# into the same framebuffer the wallet is painting.
_KDSETMODE = 0x4B3A
# FBIOBLANK with FB_BLANK_UNBLANK. Writes alone do not start the panel
# CRTC when the console is on HDMI.
_FBIOBLANK = 0x4611
_FB_BLANK_UNBLANK = 0
_KD_TEXT = 0
_KD_GRAPHICS = 1
_CONSOLE_TTY = "/dev/tty0"
_CURSOR_BLINK = "/sys/class/graphics/fbcon/cursor_blink"


class ConsoleClaim:
    """Hold on the Linux console while a framebuffer app owns the panel."""

    def __init__(self) -> None:
        self.tty_fd: int | None = None
        self.blink_off = False

    def release(self) -> None:
        import fcntl
        import os

        if self.tty_fd is not None:
            with contextlib.suppress(OSError):
                fcntl.ioctl(self.tty_fd, _KDSETMODE, _KD_TEXT)
            os.close(self.tty_fd)
            self.tty_fd = None
        if self.blink_off:
            with contextlib.suppress(OSError):
                with open(_CURSOR_BLINK, "w", encoding="ascii") as blink:
                    blink.write("1\n")
            self.blink_off = False


def claim_linux_console() -> ConsoleClaim:
    """Stop the console cursor from drawing over the panel.

    Graphics mode is the real handoff: the kernel leaves the framebuffer
    alone until the claim is released. Turning blink off is the fallback
    when this user cannot open the console.
    """
    import fcntl
    import os
    import sys

    claim = ConsoleClaim()
    # Group tty can write this device, not read it. The graphics-mode
    # ioctl still needs CAP_SYS_TTY_CONFIG or a session whose controlling
    # terminal is this console. An SSH login has neither, so usermod
    # cannot clear the cursor.
    tty_error: OSError | None = None
    try:
        tty = os.open(_CONSOLE_TTY, os.O_WRONLY | os.O_NOCTTY)
    except OSError as exc:
        tty = None
        tty_error = exc
    if tty is not None:
        try:
            fcntl.ioctl(tty, _KDSETMODE, _KD_GRAPHICS)
        except OSError as exc:
            tty_error = exc
            os.close(tty)
        else:
            claim.tty_fd = tty
            return claim
    try:
        with open(_CURSOR_BLINK, "w", encoding="ascii") as blink:
            blink.write("0\n")
    except OSError as exc:
        print(
            "Could not hide the console cursor "
            f"({tty_error or exc}). The wallet is still starting.\n"
            "From the Pi, run this once, then start the wallet again:\n"
            "  sudo python3 -c 'import os,fcntl; "
            "fd=os.open(\"/dev/tty0\", os.O_RDWR); fcntl.ioctl(fd, 0x4B3A, 1)'",
            file=sys.stderr,
        )
        return claim
    claim.blink_off = True
    return claim


class FramebufferDisplay(Display):
    """Write frames to a Linux framebuffer. No X server.

    Width and height come from the device profile. The kernel's reported
    size wins when the ioctl succeeds, so a panel that disagrees with the
    profile fails loudly instead of painting off the edge. The Linux
    console on that same framebuffer is switched to graphics mode so its
    cursor does not blink through the frame.
    """

    def __init__(self, path: str, width: int, height: int) -> None:
        self.path = path
        self.width = width
        self.height = height
        self._fd: int | None = None
        self._bpp = 16
        self._console = ConsoleClaim()
        self._open()
        self._console = claim_linux_console()

    def _open(self) -> None:
        import fcntl
        import os
        import struct

        try:
            fd = os.open(self.path, os.O_RDWR)
        except OSError as exc:
            raise RuntimeError(f"cannot open framebuffer {self.path}: {exc}") from exc
        self._fd = fd
        # FBIOGET_VSCREENINFO. The first seven fields are __u32 on every
        # architecture: xres, yres, xres_virtual, yres_virtual, xoffset,
        # yoffset, bits_per_pixel.
        buf = bytearray(160)
        try:
            fcntl.ioctl(fd, 0x4600, buf)
        except OSError as exc:
            os.close(fd)
            self._fd = None
            raise RuntimeError(f"FBIOGET_VSCREENINFO failed on {self.path}: {exc}") from exc
        xres, yres, _xv, _yv, _xo, _yo, bpp = struct.unpack_from("<7I", buf)
        if (xres, yres) != (self.width, self.height):
            os.close(fd)
            self._fd = None
            raise RuntimeError(
                f"{self.path} is {xres}x{yres}, profile expects "
                f"{self.width}x{self.height}"
            )
        if bpp not in (16, 32):
            os.close(fd)
            self._fd = None
            raise RuntimeError(f"{self.path} bits_per_pixel={bpp}, want 16 or 32")
        self._bpp = bpp
        try:
            fcntl.ioctl(fd, _FBIOBLANK, _FB_BLANK_UNBLANK)
        except OSError as exc:
            logger.warning("unblank %s failed: %s", self.path, exc)
        logger.info("framebuffer %s %dx%d %dbpp", self.path, xres, yres, bpp)

    def flip(self, framebuf: FrameBuffer) -> None:
        if self._fd is None:
            raise RuntimeError("framebuffer is closed")
        if framebuf.size != (self.width, self.height):
            raise ValueError(
                f"framebuf size {framebuf.size} does not match display "
                f"{(self.width, self.height)}"
            )
        import os

        img = framebuf.image
        if self.brightness < MAX_BRIGHTNESS:
            from PIL import ImageEnhance

            img = ImageEnhance.Brightness(img).enhance(self.brightness)
        payload = rgb_to_fb_bytes(img, self._bpp)
        os.lseek(self._fd, 0, os.SEEK_SET)
        os.write(self._fd, payload)

    def close(self) -> None:
        self._console.release()
        if self._fd is None:
            return
        import os

        os.close(self._fd)
        self._fd = None


def open_display(backend: str = "auto", *, fb_device: str = "/dev/fb1", width: int = 480, height: int = 320) -> Display:
    """Construct a display backend.

    ``backend`` can be:

    * ``"auto"``      — try ST7789; fall back to headless if the
                        Adafruit stack isn't importable. Useful when
                        the same script runs on the Pi *and* the dev
                        laptop.
    * ``"st7789"``    — force the real ST7789. Raises if unavailable.
    * ``"headless"``  — always use the in-memory backend.
    """
    if backend == "headless":
        return HeadlessDisplay()
    if backend == "st7789":
        return ST7789Display()
    if backend == "framebuffer":
        return FramebufferDisplay(fb_device, width, height)
    if backend == "auto":
        try:
            return ST7789Display()
        except RuntimeError as exc:
            # Visible at WARNING by default — without this, a Pi with
            # missing display extras boots cleanly into HeadlessDisplay
            # and the panel stays dark with no journal trace. The
            # production systemd unit pins --display st7789 to fail
            # loudly instead, but this branch still exists for the
            # `piwallet bonnet` CLI on a dev laptop, where the
            # downgrade is intentional.
            logger.warning(
                "ST7789 display unavailable, falling back to "
                "HeadlessDisplay: %s",
                exc,
            )
            return HeadlessDisplay()
    raise ValueError(f"unknown display backend: {backend!r}")

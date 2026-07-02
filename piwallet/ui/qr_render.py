"""Render a QR code into a PIL image, scaled to fit a square pixel target.

Used by bonnet screens that need to display short payloads (BSV
addresses, animated PW1 frames from envelope blobs, etc.) on the
240x240 panel.

We use ``segno`` because it's pure Python (no native deps on the Pi)
and gives us direct access to the matrix iterator, which lets us
control pixel quantization precisely.

Render cost on a Pi Zero 2 W is dominated by the per-pixel Python
loop (tens of thousands of writes for an xpub QR at ~176 px). To keep
the bonnet UI responsive we cache the resulting :class:`PIL.Image`
keyed on the full render parameter tuple — animated multipart-QR
screens redraw the same handful of frames at ~30 fps, and address
screens redraw the same single QR until the index changes.

Cache invariants:

- The cache is bounded (``_QR_CACHE_MAX``) and uses LRU eviction so a
  long-lived bonnet process can't OOM from accumulated frames.
- Returned images **must not be mutated** by callers. ``paste_qr``
  composites onto a destination buffer without touching the QR.
- ``clear_qr_cache()`` is exposed for tests and for explicit cleanup
  on screen transitions.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable

import segno
from PIL import Image

from piwallet.ui.display import DISPLAY_HEIGHT, DISPLAY_WIDTH, FrameBuffer

#: Maximum number of cached QR renders. PW1 multipart sequences for an
#: xpub_export envelope are typically <= 16 frames; address screens
#: keep one per index. 64 leaves comfortable headroom while bounding
#: peak memory at roughly ``64 * 240 * 240 * 3 ≈ 11 MB`` worst case.
_QR_CACHE_MAX: int = 64

#: "Light" pixel value used for the QR background and the on-modules'
#: complement. Deliberately *not* pure ``(255, 255, 255)``.
#:
#: Rationale: the bonnet's 240x240 ST7789 LCD at full backlight emits
#: enough light through pure-white pixels that camera auto-exposure
#: clips them and can't lock a clean binarisation threshold —
#: especially for the dense multipart frames (v6, ~4 px/module).
#: Symptoms reported on hardware: "brightness all the way up, won't
#: scan; turn brightness down, scans fine."
#:
#: Tuning history:
#:
#: * ``(255, 255, 255)`` — pure white, blooms hard on every camera.
#: * ``(208, 208, 208)`` — ~80% luminance, fixed phone scanning of
#: the xpub_export pairing QR.
#: * ``(170, 170, 170)`` — ~67% luminance, fixed *most* laptop
#: webcams; some still saturated.
#: * ``(140, 140, 140)`` — ~55% luminance; fixed laptop webcams but
#: many phone cameras still clipped the quiet zone when the QR sat
#: on an otherwise black screen (AE boosts gain → grey reads white).
#: * ``(100, 100, 100)`` — ~39% luminance; matte plate helped phones but
#: still hot for some panels.
#: * **62** — default (~24% luminance). Live UP/DOWN on QR
#: screens adjusts ``BonnetSettings.qr_background`` in steps of 31.
#:
#: Tune downward if a particular panel still blooms; tune *up* and
#: things get worse, never better.
from piwallet.ui.qr_brightness import DEFAULT_QR_BACKGROUND, qr_background_rgb

QR_LIGHT_BG: tuple[int, int, int] = qr_background_rgb(DEFAULT_QR_BACKGROUND)

#: Default outward padding for :func:`paste_qr_matte` — wide enough
#: that a phone framing the QR also sees mostly grey, not black UI.
QR_MATTE_PAD: int = 20

#: Height of the bottom control bar on QR screens (footer hints).
QR_PANEL_FOOTER_H: int = 22


def qr_panel_content_bottom_y() -> int:
    """Y coordinate where the grey QR panel ends (above the footer bar)."""
    return DISPLAY_HEIGHT - QR_PANEL_FOOTER_H


def fill_qr_panel_background(
    fb: FrameBuffer,
    *,
    top_y: int,
    matte_color: tuple[int, int, int],
    bottom_y: int | None = None,
) -> None:
    """Fill the main content band with the scan-friendly QR grey background."""
    y1 = bottom_y if bottom_y is not None else qr_panel_content_bottom_y()
    fb.draw.rectangle((0, top_y, DISPLAY_WIDTH, y1), fill=matte_color)


#: Module-private LRU cache keyed on ``(data, target_px, border, fg, bg, error)``.
#: ``OrderedDict`` gives O(1) insertion + ``move_to_end`` for cache hits.
_qr_cache: OrderedDict[tuple, Image.Image] = OrderedDict()


def render_qr(
    data: str | bytes,
    *,
    target_px: int,
    border: int = 2,
    fg: tuple[int, int, int] = (0, 0, 0),
    bg: tuple[int, int, int] = QR_LIGHT_BG,
    error: str = "L",
) -> Image.Image:
    """Encode ``data`` as a QR code and scale it to ``target_px`` pixels.

    The output is a square ``PIL.Image`` of size ``(target_px, target_px)``
    in ``RGB`` mode, drawn with integer-multiple module sizes so the
    result stays crisp on the 240x240 panel (no fractional pixels).

    ``border`` is the QR quiet-zone width in modules (the QR spec
    recommends 4 but 2 is fine on a small panel where every pixel
    counts). Do *not* drop below 2 — phone scanners need the quiet
    zone to find the finder patterns.

    ``bg`` defaults to :data:`QR_LIGHT_BG` rather than pure white to
    avoid camera-sensor saturation on the bright ST7789 panel; pass
    ``(255, 255, 255)`` explicitly only when you really want pure
    white (e.g. to render to a host-side PNG that will be printed
    rather than displayed).

    ``error`` is the QR error-correction level: ``"L"``, ``"M"``,
    ``"Q"``, or ``"H"``.

    Repeated calls with identical arguments return the same cached
    image instance (do not mutate it — see module docstring).
    """
    if target_px < 32:
        raise ValueError(f"target_px must be >= 32, got {target_px}")

    key: tuple = (data, target_px, border, fg, bg, error)
    cached = _qr_cache.get(key)
    if cached is not None:
        _qr_cache.move_to_end(key)
        return cached

    img = _render_qr_uncached(
        data,
        target_px=target_px,
        border=border,
        fg=fg,
        bg=bg,
        error=error,
    )
    _qr_cache[key] = img
    if len(_qr_cache) > _QR_CACHE_MAX:
        _qr_cache.popitem(last=False)
    return img


def _render_qr_uncached(
    data: str | bytes,
    *,
    target_px: int,
    border: int,
    fg: tuple[int, int, int],
    bg: tuple[int, int, int],
    error: str,
) -> Image.Image:
    """Slow path: encode + draw a fresh QR image. Used by the cache miss branch."""
    payload: object
    if isinstance(data, bytes):
        # segno wants bytes through the explicit `bytes` argument so it
        # encodes them as byte mode (binary).
        payload = data
    else:
        payload = data

    qr = segno.make(payload, error=error, micro=False)
    matrix: Iterable[Iterable[int]] = qr.matrix
    rows = list(matrix)
    modules = len(rows)
    if modules == 0:
        raise RuntimeError("segno produced an empty QR matrix")

    bordered = modules + 2 * border
    scale = max(1, target_px // bordered)
    inner_px = scale * modules
    pad_px = (target_px - inner_px) // 2

    img = Image.new("RGB", (target_px, target_px), bg)
    pixels = img.load()

    for y, row in enumerate(rows):
        for x, on in enumerate(row):
            if not on:
                continue
            for dy in range(scale):
                for dx in range(scale):
                    px = pad_px + x * scale + dx
                    py = pad_px + y * scale + dy
                    if 0 <= px < target_px and 0 <= py < target_px:
                        pixels[px, py] = fg
    return img


def clear_qr_cache() -> None:
    """Drop every cached render. Tests + explicit cleanup paths use this."""
    _qr_cache.clear()


def qr_cache_size() -> int:
    """Return the current number of cached entries (testing aid)."""
    return len(_qr_cache)


def paste_qr(
    fb_image: Image.Image,
    qr_image: Image.Image,
    *,
    x: int,
    y: int,
) -> None:
    """Composite ``qr_image`` onto ``fb_image`` at the given top-left."""
    fb_image.paste(qr_image, (x, y))


def paste_qr_matte(
    fb_image: Image.Image,
    qr_image: Image.Image,
    *,
    x: int,
    y: int,
    matte_pad: int = QR_MATTE_PAD,
    matte_color: tuple[int, int, int] = QR_LIGHT_BG,
) -> None:
    """Paint a grey scan plate, then composite the QR on top.

    Phone cameras auto-expose for the whole frame. A grey QR on a black
    bonnet screen reads as a bright blob and the quiet zone clips to
    white. Extending :data:`QR_LIGHT_BG` outward gives AE a mid-tone
    field so black modules stay separable from the background.
    """
    w, h = qr_image.size
    x0 = max(0, x - matte_pad)
    y0 = max(0, y - matte_pad)
    x1 = min(fb_image.width, x + w + matte_pad)
    y1 = min(fb_image.height, y + h + matte_pad)
    from PIL import ImageDraw

    ImageDraw.Draw(fb_image).rectangle((x0, y0, x1, y1), fill=matte_color)
    paste_qr(fb_image, qr_image, x=x, y=y)

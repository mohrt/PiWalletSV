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

#: Maximum number of cached QR renders. PW1 multipart sequences for an
#: xpub_export envelope are typically <= 16 frames; address screens
#: keep one per index. 64 leaves comfortable headroom while bounding
#: peak memory at roughly ``64 * 240 * 240 * 3 ≈ 11 MB`` worst case.
_QR_CACHE_MAX: int = 64

#: Module-private LRU cache keyed on ``(data, target_px, border, fg, bg, error)``.
#: ``OrderedDict`` gives O(1) insertion + ``move_to_end`` for cache hits.
_qr_cache: OrderedDict[tuple, Image.Image] = OrderedDict()


def render_qr(
    data: str | bytes,
    *,
    target_px: int,
    border: int = 2,
    fg: tuple[int, int, int] = (0, 0, 0),
    bg: tuple[int, int, int] = (255, 255, 255),
    error: str = "L",
) -> Image.Image:
    """Encode ``data`` as a QR code and scale it to ``target_px`` pixels.

    The output is a square ``PIL.Image`` of size ``(target_px, target_px)``
    in ``RGB`` mode, drawn with integer-multiple module sizes so the
    result stays crisp on the 240x240 panel (no fractional pixels).

    ``border`` is the QR quiet-zone width in modules (the QR spec
    recommends 4 but 2 is fine on a small panel where every pixel
    counts).

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

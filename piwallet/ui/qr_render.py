"""Render a QR code into a PIL image, scaled to fit a square pixel target.

Used by bonnet screens that need to display short payloads (BSV
addresses, animated PW1 frames from envelope blobs, etc.) on the
240x240 panel.

We use ``segno`` because it's pure Python (no native deps on the Pi)
and gives us direct access to the matrix iterator, which lets us
control pixel quantization precisely.
"""

from __future__ import annotations

from collections.abc import Iterable

import segno
from PIL import Image


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
    """
    if target_px < 32:
        raise ValueError(f"target_px must be >= 32, got {target_px}")

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
    # Integer scale: how many display pixels per QR module?
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


def paste_qr(
    fb_image: Image.Image,
    qr_image: Image.Image,
    *,
    x: int,
    y: int,
) -> None:
    """Composite ``qr_image`` onto ``fb_image`` at the given top-left."""
    fb_image.paste(qr_image, (x, y))

"""Scale camera RGB frames for small TFT previews (RGB888 → PIL thumbnails)."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageOps


def rgb888_thumbnail(rgb: np.ndarray, *, max_edge: int = 208) -> Image.Image:
    """Return RGB image scaled to fit inside max_edge x max_edge (contain, bilinear).

    ``rgb`` should be Picamera2 ``RGB888`` (H x W x 3 uint8); extra channels strip to RGB.
    """
    if rgb.dtype != np.uint8:
        rgb = rgb.astype(np.uint8, copy=False)
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        raise ValueError(f"expected H x W x 3 RGB array, got shape {rgb.shape}")
    base = rgb[:, :, :3]
    if not base.flags["C_CONTIGUOUS"]:
        base = np.ascontiguousarray(base)
    pil = Image.fromarray(base, mode="RGB")
    return ImageOps.contain(pil, (max_edge, max_edge), Image.Resampling.BILINEAR)


def paste_cover(fb_img: Image.Image, thumb: Image.Image, box: tuple[int, int, int, int]) -> None:
    """Letterbox-fit ``thumb`` into (left, top, right, bottom); fill margins with black."""
    left, top, right, bot = box
    w, h = right - left, bot - top
    if w <= 0 or h <= 0:
        return
    fitted = ImageOps.contain(thumb, (w, h), Image.Resampling.BILINEAR)
    xoff = left + (w - fitted.width) // 2
    yoff = top + (h - fitted.height) // 2
    fb_img.paste((0, 0, 0), (left, top, right, bot))
    fb_img.paste(fitted, (xoff, yoff))

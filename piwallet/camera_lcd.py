"""Scale camera RGB frames for small TFT previews (RGB888 → PIL thumbnails)."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageOps

# PiWallet case mounts the camera PCB with the sensor 90° off from the bonnet
# LCD. Rotate captured frames so the sign-flow preview reads upright.
PIWALLET_CAMERA_ROTATION_DEG: int = 90


def rotate_rgb888(rgb: np.ndarray, degrees: int = PIWALLET_CAMERA_ROTATION_DEG) -> np.ndarray:
    """Rotate an H×W×3 RGB888 array clockwise by 0/90/180/270° (0 = no-op)."""
    if degrees == 0:
        return rgb
    if degrees not in (90, 180, 270):
        raise ValueError(f"degrees must be 0/90/180/270, got {degrees}")
    if rgb.dtype != np.uint8:
        rgb = rgb.astype(np.uint8, copy=False)
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        raise ValueError(f"expected H x W x 3 RGB array, got shape {rgb.shape}")
    base = rgb[:, :, :3]
    if not base.flags["C_CONTIGUOUS"]:
        base = np.ascontiguousarray(base)
    pil = Image.fromarray(base, mode="RGB")
    pil = pil.transpose(
        {
            90: Image.Transpose.ROTATE_270,
            180: Image.Transpose.ROTATE_180,
            270: Image.Transpose.ROTATE_90,
        }[degrees]
    )
    return np.asarray(pil)


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

"""Tests for RGB → TFT thumbnail helpers."""

from __future__ import annotations

import numpy as np
from PIL import Image

from piwallet.camera_lcd import paste_cover, rgb888_thumbnail


def test_rgb888_thumbnail_contains_max_edge() -> None:
    rgb = np.zeros((100, 200, 3), dtype=np.uint8)
    rgb[:, :, 0] = 200
    t = rgb888_thumbnail(rgb, max_edge=120)
    assert max(t.size) <= 120
    assert t.mode == "RGB"


def test_paste_cover_letterboxed() -> None:
    fb = Image.new("RGB", (60, 40), color=(255, 0, 0))
    thumb = Image.new("RGB", (20, 20), color=(0, 255, 0))
    paste_cover(fb, thumb, box=(10, 5, 50, 35))
    cx, cy = 30, 20
    assert fb.getpixel((cx, cy))[:3] == (0, 255, 0)


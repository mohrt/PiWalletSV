#!/usr/bin/env python3
"""Generate the project's logo asset set from a single master PNG.

Inputs
------
- ``docs/assets/logo-master.png`` — the canonical artwork (portrait
  orientation; shield+dragon in the upper portion, ``PiWalletSV``
  wordmark below). Anything you upload as the new logo should overwrite
  this file; running this script regenerates every derivative below.

Outputs
-------
- ``docs/assets/logo.png`` — full image w/ wordmark, scaled to 1200 px tall.
  Used by mkdocs ``theme.logo`` and any marketing-site hero placement.
- ``docs/assets/favicon.png`` — 32×32 square shield-only crop. Used by
  mkdocs ``theme.favicon``.
- ``companion/public/favicon-32.png``      — 32×32  square (browser tab).
- ``companion/public/favicon-192.png``     — 192×192 (Android home-screen).
- ``companion/public/favicon-512.png``     — 512×512 (PWA splash, store).
- ``companion/public/apple-touch-icon.png``— 180×180 (iOS home-screen).
- ``companion/public/logo.png``            — full image (1200 px tall),
  available to the companion if it ever wants to render a banner /
  about page itself.

Why two pipelines (full vs square)?
-----------------------------------
The master art is portrait with a wordmark below the shield. Tiny icons
(favicon, PWA install tile) need the wordmark *removed* — text is
unreadable below ~64 px and ends up looking like a glitch. The square
crop covers exactly the shield+dragon region, so a 32×32 favicon still
reads as "the dragon mark", while the marketing surfaces (which have
plenty of room) keep the wordmark.

If you change the master, eyeball the ``SHIELD_BOTTOM_FRAC`` constant
below — it controls where the square crop's bottom edge lands. The
default (0.78) matches the supplied alpha-1 artwork.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

# Repo root. Resolved from this script's location so the script works
# whether run via `python scripts/build-logo-assets.py` or `./scripts/...`.
ROOT = Path(__file__).resolve().parent.parent

MASTER = ROOT / "docs" / "assets" / "logo-master.png"

# Vertical centre of the shield+dragon mark, expressed as a fraction of
# master image height. The supplied alpha-1 artwork has the dragon's
# spikes at ~y=75 and the shield bottom at ~y=775 in a 1024-tall image;
# the visual centre therefore lands at ~y=430 → 430 / 1024 ≈ 0.42.
#
# If you swap the master for new art, re-eyeball this. A wrong value
# either slices off the bottom of the shield (too small) or pulls the
# wordmark into the crop (too large).
SHIELD_CENTRE_FRAC = 0.42

# Marketing-header height. mkdocs scales via CSS so the source just needs
# to be high enough not to look pixelated on retina screens at the
# default header height (~64 px ⇒ 128 px @2x, 192 px @3x). 1200 leaves
# generous headroom and a usable hero/about-page asset.
FULL_HEIGHT_PX = 1200

# Per-output target sizes (width × height in px). All square crops
# derive from the same shield-only intermediate.
SQUARE_TARGETS: dict[Path, int] = {
    ROOT / "docs" / "assets" / "favicon.png":           32,
    ROOT / "companion" / "public" / "favicon-32.png":   32,
    ROOT / "companion" / "public" / "favicon-192.png":  192,
    ROOT / "companion" / "public" / "favicon-512.png":  512,
    ROOT / "companion" / "public" / "apple-touch-icon.png": 180,
}

# Per-output target heights (full master, scaled). Width auto-derives
# from the master aspect ratio.
FULL_TARGETS: dict[Path, int] = {
    ROOT / "docs" / "assets" / "logo.png":          FULL_HEIGHT_PX,
    ROOT / "companion" / "public" / "logo.png":     FULL_HEIGHT_PX,
}


def _scaled_full(master: Image.Image, target_h: int) -> Image.Image:
    w, h = master.size
    target_w = int(round(w * target_h / h))
    # LANCZOS = highest-quality downscale Pillow ships; the source is
    # 1024 px tall so 1200 is technically an upscale (small) but the
    # interpolation stays clean for PNG art.
    return master.resize((target_w, target_h), Image.LANCZOS)


def _square_shield(master: Image.Image) -> Image.Image:
    """Square crop framed on the shield+dragon (no wordmark).

    Anchored on a vertical centre fraction (``SHIELD_CENTRE_FRAC``)
    rather than the geometric image centre — the wordmark below the
    shield pulls the geometric centre downward, so a naive centre crop
    leaves empty space above the dragon and clips the shield's bottom
    point. Side length is the smaller of the image width and the
    available vertical band, so the crop never escapes the canvas.
    """
    w, h = master.size
    centre_y = int(round(h * SHIELD_CENTRE_FRAC))
    centre_x = w // 2

    # Largest square that fits with the requested centre still inside
    # the canvas. For the supplied 687×1024 master this resolves to
    # 687 (width-limited).
    half = min(centre_x, w - centre_x, centre_y, h - centre_y)
    side = 2 * half

    left = centre_x - half
    top = centre_y - half
    return master.crop((left, top, left + side, top + side))


def main() -> int:
    if not MASTER.exists():
        print(f"error: master logo not found at {MASTER}", file=sys.stderr)
        print("       drop the source PNG there and re-run.", file=sys.stderr)
        return 2

    master = Image.open(MASTER).convert("RGBA")
    print(f"master: {MASTER.relative_to(ROOT)}  ({master.size[0]}x{master.size[1]})")

    shield = _square_shield(master)
    print(f"  shield-only crop: {shield.size[0]}x{shield.size[1]}")

    for out, side in SQUARE_TARGETS.items():
        out.parent.mkdir(parents=True, exist_ok=True)
        img = shield.resize((side, side), Image.LANCZOS)
        img.save(out, format="PNG", optimize=True)
        print(f"  -> {out.relative_to(ROOT)}  ({side}x{side})")

    for out, target_h in FULL_TARGETS.items():
        out.parent.mkdir(parents=True, exist_ok=True)
        img = _scaled_full(master, target_h)
        img.save(out, format="PNG", optimize=True)
        print(f"  -> {out.relative_to(ROOT)}  ({img.size[0]}x{img.size[1]})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

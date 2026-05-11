#!/usr/bin/env python
"""Dump PNG previews of each bonnet screen for design review.

Renders every screen the bonnet boot loop can show into a 240x240
PNG file, then exits. Useful for eyeballing layout, color, and font
fit before pushing to the Pi.

Usage::

    python scripts/preview_bonnet_screens.py --out /tmp/bonnet-previews

Each output filename is prefixed with an integer ordering matches the
real user flow.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from piwallet.bonnet.unlock import UnlockScreen
from piwallet.bonnet.wallet_detail import WalletDetailScreen
from piwallet.bonnet.wallet_list import WalletListScreen
from piwallet.core.vault import WalletRecord
from piwallet.firstboot.disclaimer import DisclaimerScreen
from piwallet.ui.display import FrameBuffer
from piwallet.ui.pin_entry import PinEntryScreen


def _save(fb: FrameBuffer, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fb.image.save(path)
    print(f"wrote {path}")


def _wallet(label: str, idx: int) -> WalletRecord:
    return WalletRecord(
        id=f"wallet-{idx}",
        label=label,
        fingerprint=bytes([idx, idx + 1, idx + 2, idx + 3]),
        derivation_path="m/44'/236'/0'",
        word_count=12,
        created_at="2026-05-10T00:00:00+00:00",
    )


def render_previews(out: Path) -> None:
    # ---- 1-3. Disclaimer pages ----------------------------------
    for i in range(3):
        fb = FrameBuffer()
        screen = DisclaimerScreen()
        screen.page = i
        screen.draw(fb)
        _save(fb, out / f"01_disclaimer_page{i + 1}.png")

    # ---- 4. PIN entry: empty ------------------------------------
    fb = FrameBuffer()
    PinEntryScreen(subtitle="").draw(fb)
    _save(fb, out / "04_pin_empty.png")

    # ---- 5. PIN entry: partially filled with attempts warning ---
    fb = FrameBuffer()
    PinEntryScreen(
        digits=[1, 2, 3, None, None, None],
        subtitle="3 attempts left",
        subtitle_color=(240, 90, 70),
    ).draw(fb)
    _save(fb, out / "05_pin_partial.png")

    # ---- 6. Unlock screen on first try --------------------------
    fb = FrameBuffer()
    UnlockScreen(verify=lambda _p: ("ok", None), attempts_remaining=10).draw(fb)
    _save(fb, out / "06_unlock_initial.png")

    # ---- 7. Wallet list -----------------------------------------
    fb = FrameBuffer()
    WalletListScreen(
        wallets=[
            _wallet("daily", 0),
            _wallet("savings", 1),
            _wallet("cold", 2),
            _wallet("test-net", 3),
        ]
    ).draw(fb)
    _save(fb, out / "07_wallet_list.png")

    # ---- 8. Wallet list empty -----------------------------------
    fb = FrameBuffer()
    WalletListScreen(wallets=[]).draw(fb)
    _save(fb, out / "08_wallet_list_empty.png")

    # ---- 9. Wallet detail with stub address ---------------------
    fb = FrameBuffer()
    detail = WalletDetailScreen(
        wallet=_wallet("daily", 0),
        derive_address=lambda c, i: "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
    )
    detail.draw(fb)
    _save(fb, out / "09_wallet_detail.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("/tmp/bonnet-previews"),  # noqa: S108 - dev script, explicit /tmp is fine
        help="Output directory (default: /tmp/bonnet-previews).",
    )
    args = parser.parse_args()
    render_previews(args.out)
    print(f"\nDone. Open {args.out} to review.")


if __name__ == "__main__":
    main()

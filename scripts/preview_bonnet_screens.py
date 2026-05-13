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

from piwallet.bonnet.choosers import WordCountChooser
from piwallet.bonnet.unlock import UnlockScreen
from piwallet.bonnet.wallet_detail import WalletDetailScreen
from piwallet.bonnet.wallet_list import WalletListScreen
from piwallet.bonnet.wallet_manage import WalletManageMenuScreen
from piwallet.core import mnemonic as mnem
from piwallet.core.vault import WalletRecord
from piwallet.firstboot.disclaimer import DisclaimerScreen
from piwallet.ui.display import FrameBuffer
from piwallet.ui.label_entry import WalletLabelEntryScreen
from piwallet.ui.pin_entry import PinEntryScreen
from piwallet.ui.show_phrase import ShowPhraseScreen
from piwallet.ui.word_entry import MnemonicEntryScreen, WordEntryScreen


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

    # ---- 9b. Wallet manage menu ---------------------------------
    fb = FrameBuffer()
    WalletManageMenuScreen(wallet=_wallet("daily", 0)).draw(fb)
    _save(fb, out / "09b_wallet_manage_menu.png")

    # ---- 9c. Wallet label editor (cursor mid-word) ---------------
    fb = FrameBuffer()
    le = WalletLabelEntryScreen(title="Rename wallet", suggested_default="savings")
    # Move cursor to the middle for a more illustrative shot.
    le.cursor = 3
    le.draw(fb)
    _save(fb, out / "09c_label_edit_cursor_mid.png")

    # ---- 10-11. Show-phrase ("write this down") -----------------
    sample_phrase = (
        "abandon ability able about above absent absorb abstract "
        "absurd abuse access accident"
    ).split()
    for i, page in enumerate([0, 1, 2]):
        fb = FrameBuffer()
        sp = ShowPhraseScreen(words=sample_phrase, per_page=4, page=page)
        sp.draw(fb)
        _save(fb, out / f"10_show_phrase_p{i + 1}.png")

    # ---- 12. Word-count chooser (restore flow) ------------------
    fb = FrameBuffer()
    WordCountChooser().draw(fb)
    _save(fb, out / "12_word_count_chooser.png")

    # ---- 13. Single word entry, fresh ---------------------------
    fb = FrameBuffer()
    WordEntryScreen(title="Word 1 of 12").draw(fb)
    _save(fb, out / "13_word_entry_empty.png")

    # ---- 14. Word entry mid-type with many matches --------------
    fb = FrameBuffer()
    s = WordEntryScreen(title="Word 1 of 12", prefix="a", candidate="b")
    s.draw(fb)
    _save(fb, out / "14_word_entry_many.png")

    # ---- 15. Word entry with exact match ------------------------
    fb = FrameBuffer()
    s = WordEntryScreen(title="Word 1 of 12", prefix="abou", candidate="t")
    s.draw(fb)
    _save(fb, out / "15_word_entry_exact.png")

    # ---- 16. Word entry with no match ---------------------------
    fb = FrameBuffer()
    s = WordEntryScreen(title="Word 3 of 12", prefix="z", candidate="z")
    s.draw(fb)
    _save(fb, out / "16_word_entry_no_match.png")

    # ---- 17. Mnemonic entry screen (delegates to current word) --
    fb = FrameBuffer()
    me = MnemonicEntryScreen(word_count=12, mode="restore")
    # advance the title to show "Word 4 of 12"
    me.words = ["abandon", "ability", "able"]
    me.current = me._new_word_screen()  # type: ignore[assignment]
    me.draw(fb)
    _save(fb, out / "17_mnemonic_entry.png")

    # ---- 18. Restore phrase review (checksum OK) -----------------
    fb = FrameBuffer()
    phrase_words = mnem.generate(12).split()
    me18 = MnemonicEntryScreen(word_count=12, mode="restore")
    me18.words = phrase_words.copy()
    me18.phase = "review"
    me18._build_review_view()
    me18.draw(fb)
    _save(fb, out / "18_restore_phrase_review.png")


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

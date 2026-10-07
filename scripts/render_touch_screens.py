"""Render Pro touch screens to PNG for the docs site.

Draws the real touch UI classes at the panel's native 320×480 and
scales each frame up with nearest-neighbour so every pixel stays sharp.

    .venv/bin/python scripts/render_touch_screens.py docs/assets/home
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from PIL import Image

from piwallet.bonnet.splash import load_logo
from piwallet.core.derivation import derive_account, master_xprv_from_seed
from piwallet.core.mnemonic import seed_from_mnemonic
from piwallet.core.vault import WalletRecord
from piwallet.touch.create import PinPad
from piwallet.touch.manage import ManageFlow
from piwallet.touch.ui import WalletHome
from piwallet.ui.display import COLOR_BG, FrameBuffer

WIDTH, HEIGHT = 320, 480
# Public BIP39 test vector; never holds funds.
TEST_PHRASE = " ".join(["abandon"] * 11 + ["about"])
TEST_PIN = "123456"
WALLETS = (
    ("savings", "main"),
    ("daily", "main"),
    ("business", "main"),
    ("donations", "main"),
    ("cold-storage", "main"),
    ("test", "test"),
    ("test-2", "test"),
    ("demo", "test"),
)


def _record(label: str, network: str, account) -> WalletRecord:
    return WalletRecord(
        id=label,
        label=label,
        fingerprint=hashlib.sha256(label.encode()).digest()[:4],
        derivation_path=account.path,
        word_count=12,
        created_at="2026-10-01T00:00:00Z",
        network=network,
    )


def splash() -> FrameBuffer:
    fb = FrameBuffer(width=WIDTH, height=HEIGHT)
    fb.clear(COLOR_BG)
    logo = load_logo(WIDTH, HEIGHT)
    fb.image.paste(logo, ((WIDTH - logo.width) // 2, (HEIGHT - logo.height) // 2))
    return fb


def pin_login() -> FrameBuffer:
    pad = PinPad(WIDTH, HEIGHT, title="Enter PIN", masked=True)
    pad.digits = TEST_PIN
    fb = FrameBuffer(width=WIDTH, height=HEIGHT)
    pad.draw(fb)
    return fb


def wallet_list(account) -> FrameBuffer:
    home = WalletHome(WIDTH, HEIGHT)
    home.set_wallets([_record(label, net, account) for label, net in WALLETS])
    fb = FrameBuffer(width=WIDTH, height=HEIGHT)
    home.draw(fb)
    return fb


def receive_qr(account) -> FrameBuffer:
    class _Vault:
        def get_account_xpub(self, pin: str, wallet_id: str) -> str:
            return str(account.xpub)

    flow = ManageFlow(WIDTH, HEIGHT, _Vault(), TEST_PIN, _record("savings", "main", account))  # type: ignore[arg-type]
    flow._open_receive()
    fb = FrameBuffer(width=WIDTH, height=HEIGHT)
    flow.draw(fb)
    return fb


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--scale", type=int, default=3)
    args = parser.parse_args()

    account = derive_account(master_xprv_from_seed(seed_from_mnemonic(TEST_PHRASE)))
    screens = {
        "piwalletpro-splash": splash(),
        "piwalletpro-pin-login": pin_login(),
        "piwalletpro-wallet-list": wallet_list(account),
        "piwalletpro-qr": receive_qr(account),
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, fb in screens.items():
        image = fb.image.resize((WIDTH * args.scale, HEIGHT * args.scale), Image.NEAREST)
        path = args.out_dir / f"{name}.png"
        image.save(path, optimize=True)
        print(path)


if __name__ == "__main__":
    main()

"""Per-wallet menu for the touch shell.

Same choices as the Zero manage list: deposit address, companion QR,
sign, info, rename, and erase. Back returns to the wallet list.
"""

from __future__ import annotations

import time

from piwallet.bonnet.companion_pairing import pairing_pw1_lines
from piwallet.core import derivation as deriv
from piwallet.core.vault import Vault, VaultError, WalletRecord
from piwallet.touch.input import Tap
from piwallet.touch.ui import AlphabetKeyboard, Hit
from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DANGER,
    COLOR_DIM,
    COLOR_FG,
    FrameBuffer,
)
from piwallet.ui.qr_brightness import (
    DEFAULT_QR_BACKGROUND,
    decrease_qr_background,
    increase_qr_background,
    qr_background_rgb,
)
from piwallet.ui.qr_render import render_qr
from piwallet.ui.widgets import draw_text, text_bbox

_ACTIONS: tuple[tuple[str, str], ...] = (
    ("receive", "Show deposit address"),
    ("companion", "Show xpub (QR)"),
    ("sign", "Sign transaction"),
    ("info", "Wallet info"),
    ("rename", "Rename"),
    ("delete", "Erase from Pi"),
)
_ROW_H = 48
_LIST_TOP = 48
_QR_FRAME_S = 0.7
# Two steps above the Zero. This panel's grey reads darker at the same level.
_QR_BG = increase_qr_background(increase_qr_background(DEFAULT_QR_BACKGROUND))
# The 320px panel fits a version-10 code at about 4 px per module, so one
# frame holds a normal xpub export. The Zero stays at 100-char chunks.
_XPUB_CHUNK = 400
_XPUB_HELP: tuple[str, ...] = (
    "Scan this with the PiWalletSV companion app to watch this wallet. "
    "The app can then show your balance and deposit addresses.",
    "This code can't spend coins, but it shows your whole wallet. Keep it private.",
)


class ManageFlow:
    """One wallet, from the menu through a single action."""

    def __init__(
        self,
        width: int,
        height: int,
        vault: Vault,
        pin: str,
        wallet: WalletRecord,
    ) -> None:
        self.width = width
        self.height = height
        self.vault = vault
        self.pin = pin
        self.wallet = wallet
        self.phase = "menu"
        self.message = ""
        self.done = False
        self.deleted = False
        self._down: str | None = None
        self._keyboard: AlphabetKeyboard | None = None
        self._index = 0
        self._address = ""
        self._qr_bg = _QR_BG
        self._xpub: deriv.Xpub | None = None
        self._frames: list[str] = []
        self._frame = 0
        self._frame_at = 0.0
        self._sign = None
        self._camera_rotation = 0

    def on_tap(self, tap: Tap) -> None:
        if self.done:
            return
        if self.phase == "menu":
            self._on_menu(tap)
        elif self.phase == "info":
            self._on_back_only(tap)
        elif self.phase == "receive":
            self._on_receive(tap)
        elif self.phase == "companion":
            self._on_companion(tap)
        elif self.phase == "sign" and self._sign is not None:
            self._sign.on_tap(tap)
            if self._sign.leave:
                self._qr_bg = self._sign.qr_bg
                self._sign = None
                self.phase = "menu"
        elif self.phase == "rename" and self._keyboard is not None:
            self._on_rename(tap)
        elif self.phase == "delete":
            self._on_delete(tap, final=False)
        elif self.phase == "delete2":
            self._on_delete(tap, final=True)

    def draw(self, fb: FrameBuffer) -> None:
        if self.phase == "info":
            self._draw_info(fb)
        elif self.phase == "receive":
            self._draw_receive(fb)
        elif self.phase == "companion":
            self._draw_companion(fb)
        elif self.phase == "sign" and self._sign is not None:
            self._sign.draw(fb)
        elif self.phase == "rename" and self._keyboard is not None:
            self._keyboard.draw(fb)
        elif self.phase in ("delete", "delete2"):
            self._draw_delete(fb)
        else:
            self._draw_menu(fb)

    def hit(self, action_id: str) -> Hit:
        for item in self._hits():
            if item.id == action_id:
                return item
        raise KeyError(action_id)

    def _hits(self) -> list[Hit]:
        if self.phase == "receive":
            return self._receive_hits()
        if self.phase == "companion":
            return self._companion_hits()
        if self.phase in ("delete", "delete2"):
            return self._delete_hits()
        if self.phase == "info":
            return [_cancel_hit(self.width)]
        hits: list[Hit] = []
        row_h = self._row_h()
        for i, (action_id, _label) in enumerate(_ACTIONS):
            y0 = _LIST_TOP + i * row_h
            hits.append(Hit(action_id, 8, y0, self.width - 8, y0 + row_h - 8))
        hits.append(_cancel_hit(self.width))
        return hits

    def _row_h(self) -> int:
        available = self.height - _LIST_TOP - 36
        return max(28, min(_ROW_H, available // len(_ACTIONS)))

    def _on_menu(self, tap: Tap) -> None:
        choice = self._release(tap)
        if choice is None:
            return
        if choice == "cancel":
            self.done = True
            return
        if choice == "info":
            self.phase = "info"
            self.message = ""
        elif choice == "receive":
            self._open_receive()
        elif choice == "rename":
            board = AlphabetKeyboard(self.width, self.height, mode="name", title="Rename")
            board.text = self.wallet.label
            self._keyboard = board
            self.phase = "rename"
            self.message = ""
        elif choice == "delete":
            self.phase = "delete"
            self.message = ""
        elif choice == "companion":
            self._open_companion()
        elif choice == "sign":
            from piwallet.touch.sign import SignScan

            self._sign = SignScan(
                self.width,
                self.height,
                camera_rotation=self._camera_rotation,
                vault=self.vault,
                pin=self.pin,
                wallet=self.wallet,
                qr_bg=self._qr_bg,
            )
            self.message = ""
            self.phase = "sign"

    def _on_back_only(self, tap: Tap) -> None:
        if self._release(tap) == "cancel":
            self.phase = "menu"

    def _on_rename(self, tap: Tap) -> None:
        assert self._keyboard is not None
        self._keyboard.on_tap(tap)
        if not self._keyboard.done:
            return
        label = (self._keyboard.result or "").strip()
        self._keyboard = None
        self.phase = "menu"
        if not label or label == self.wallet.label.strip():
            return
        try:
            self.vault.rename_wallet(self.pin, self.wallet.id, label)
        except VaultError as exc:
            self.message = str(exc)[:48]
            return
        fresh = next((w for w in self.vault.list_wallets() if w.id == self.wallet.id), None)
        if fresh is not None:
            self.wallet = fresh

    def _on_delete(self, tap: Tap, *, final: bool) -> None:
        choice = self._release(tap)
        if choice is None:
            return
        if choice == "cancel":
            self.phase = "menu"
            return
        if choice != "erase":
            return
        if not final:
            self.phase = "delete2"
            return
        try:
            self.vault.remove_wallet(self.pin, self.wallet.id)
        except VaultError as exc:
            self.phase = "menu"
            self.message = str(exc)[:48]
            return
        self.deleted = True
        self.done = True

    def _open_receive(self) -> None:
        try:
            if self._xpub is None:
                self._xpub = deriv.parse_xpub(
                    self.vault.get_account_xpub(self.pin, self.wallet.id)
                )
            self._address = deriv.derive_address(
                self._xpub, 0, self._index, network=self.wallet.network
            )
        except VaultError as exc:
            self.message = str(exc)[:48]
            self.phase = "menu"
            return
        self.phase = "receive"
        self.message = ""

    def _open_companion(self) -> None:
        try:
            frames = pairing_pw1_lines(
                self.vault, self.pin, self.wallet, chunk_chars=_XPUB_CHUNK
            )
        except VaultError as exc:
            self.message = str(exc)[:48]
            self.phase = "menu"
            return
        if not frames:
            self.message = "No QR data."
            self.phase = "menu"
            return
        self._frames = frames
        self._frame = 0
        self._frame_at = time.monotonic()
        self.phase = "companion"
        self.message = ""

    def tick(self) -> bool:
        """Repaint when an xpub frame or the camera preview changes."""
        changed = self.advance_qr()
        if self._sign is not None and self._sign.poll():
            changed = True
        return changed

    def advance_qr(self) -> bool:
        """Step the xpub QR when its frame time has elapsed."""
        if self.phase != "companion" or len(self._frames) < 2:
            return False
        now = time.monotonic()
        if now < self._frame_at + _QR_FRAME_S:
            return False
        self._frame = (self._frame + 1) % len(self._frames)
        self._frame_at = now
        return True

    def _on_companion(self, tap: Tap) -> None:
        choice = self._release(tap)
        if choice is None:
            return
        if choice == "cancel":
            self._frames = []
            self.phase = "menu"
            return
        if choice == "brighter":
            self._qr_bg = increase_qr_background(self._qr_bg)
        elif choice == "dimmer":
            self._qr_bg = decrease_qr_background(self._qr_bg)
        else:
            return
        self._frame = 0
        self._frame_at = time.monotonic()

    def _on_receive(self, tap: Tap) -> None:
        choice = self._release(tap)
        if choice is None:
            return
        if choice == "cancel":
            self.phase = "menu"
            return
        if choice == "brighter":
            self._qr_bg = increase_qr_background(self._qr_bg)
            return
        if choice == "dimmer":
            self._qr_bg = decrease_qr_background(self._qr_bg)
            return
        if choice == "prev" and self._index > 0:
            self._index -= 1
        elif choice == "next":
            self._index += 1
        else:
            return
        self._open_receive()

    def _release(self, tap: Tap) -> str | None:
        hit = self._at(tap.x, tap.y)
        if tap.pressed:
            self._down = hit
            return None
        chosen = self._down
        self._down = None
        if chosen is not None and chosen == hit:
            return chosen
        return None

    def _at(self, x: int, y: int) -> str | None:
        for item in self._hits():
            if item.contains(x, y):
                return item.id
        return None

    def _draw_menu(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        label = self.wallet.label.strip() or "wallet"
        draw_text(fb, 12, 8, _fit(label, self.width - 140, 18), size=18, color=COLOR_FG)
        _draw_cancel(fb, self.width, held=self._down == "cancel", label="Back")
        labels = dict(_ACTIONS)
        for item in self._hits():
            if item.id == "cancel":
                continue
            held = item.id == self._down
            _button(fb, item, labels[item.id], held=held, danger=item.id == "delete")
        if self.message:
            draw_text(fb, 16, self.height - 28, self.message, size=15, color=COLOR_DIM)

    def _draw_info(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        label = self.wallet.label.strip() or "wallet"
        draw_text(fb, 12, 8, _fit(label, self.width - 140, 18), size=18, color=COLOR_FG)
        _draw_cancel(fb, self.width, held=self._down == "cancel", label="Back")
        net = "testnet" if self.wallet.network == "test" else "mainnet"
        created = self.wallet.created_at.split("T", 1)[0]
        rows = (
            ("Network", net),
            ("HD path", self.wallet.derivation_path),
            ("Fingerprint", self.wallet.fingerprint.hex()),
            ("Words", str(self.wallet.word_count)),
            ("Created", created),
        )
        y = 56
        for key, value in rows:
            draw_text(fb, 16, y, key, size=14, color=COLOR_DIM)
            draw_text(fb, 16, y + 18, value, size=16, color=COLOR_FG)
            y += 48

    def _draw_receive(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        draw_text(fb, 12, 8, f"Address {self._index + 1}", size=18, color=COLOR_FG)
        _draw_cancel(fb, self.width, held=self._down == "cancel", label="Back")
        if self._address:
            qr_x, qr_y, side, _bright, _dim = self._qr_layout()
            qr = render_qr(
                self._address,
                target_px=side,
                bg=qr_background_rgb(self._qr_bg),
            )
            fb.image.paste(qr, (qr_x, qr_y))
            y = qr_y + qr.height + 8
            size = _address_size(self._address, self.width - 16)
            draw_text(
                fb,
                (self.width - _width(self._address, size)) // 2,
                y,
                self._address,
                size=size,
                color=COLOR_FG,
            )
        for item in self._receive_hits():
            if item.id == "cancel":
                continue
            if item.id in ("brighter", "dimmer"):
                _icon_button(fb, item, item.id, held=item.id == self._down)
                continue
            _nav_button(fb, item, held=item.id == self._down)

    def _draw_companion(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        count = len(self._frames)
        title = f"Xpub {self._frame + 1}/{count}" if count else "Xpub"
        draw_text(fb, 12, 8, _fit(title, self.width - 140, 18), size=18, color=COLOR_FG)
        _draw_cancel(fb, self.width, held=self._down == "cancel", label="Back")
        if not self._frames:
            return
        qr_x, qr_y, side, _bright, _dim = self._qr_layout()
        qr = render_qr(
            self._frames[self._frame],
            target_px=side,
            error="L",
            bg=qr_background_rgb(self._qr_bg),
        )
        fb.image.paste(qr, (qr_x, qr_y))
        y = qr_y + qr.height + 12
        for paragraph in _XPUB_HELP:
            for line in _wrap(paragraph, self.width - 32, 15):
                draw_text(fb, 16, y, line, size=15, color=COLOR_DIM)
                y += 20
            y += 8
        for item in self._companion_hits():
            if item.id == "cancel":
                continue
            _icon_button(fb, item, item.id, held=item.id == self._down)

    def _draw_delete(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        final = self.phase == "delete2"
        draw_text(fb, 12, 8, "Last chance" if final else "Erase wallet?", size=18, color=COLOR_FG)
        _draw_cancel(fb, self.width, held=self._down == "cancel")
        body = (
            "This removes the wallet from this device. The coins stay on the chain. "
            "The seed phrase is the only way to spend them later."
            if not final
            else "Erase this wallet from the device. This cannot be undone."
        )
        y = 52
        for line in _wrap(body, self.width - 32, 15):
            draw_text(fb, 16, y, line, size=15, color=COLOR_DIM)
            y += 20
        for item in self._delete_hits():
            if item.id == "cancel":
                continue
            label = "Erase permanently" if final else "Erase"
            _button(fb, item, label, held=item.id == self._down, danger=True)

    def _qr_layout(self) -> tuple[int, int, int, Hit, Hit]:
        btn = 44
        gap = 8
        btn_x1 = self.width - 8
        btn_x0 = btn_x1 - btn
        qr_left = 12
        qr_right = btn_x0 - gap
        side = max(80, qr_right - qr_left)
        qr_x = qr_left + (qr_right - qr_left - side) // 2
        qr_y = 44
        pair = btn * 2 + gap
        top = qr_y + max(0, (side - pair) // 2)
        brighter = Hit("brighter", btn_x0, top, btn_x1, top + btn)
        dimmer = Hit("dimmer", btn_x0, top + btn + gap, btn_x1, top + pair)
        return qr_x, qr_y, side, brighter, dimmer

    def _receive_hits(self) -> list[Hit]:
        y = self.height - 48
        mid = self.width // 2
        _qr_x, _qr_y, _side, brighter, dimmer = self._qr_layout()
        return [
            Hit("prev", 4, y, mid - 4, self.height - 6),
            Hit("next", mid + 4, y, self.width - 4, self.height - 6),
            brighter,
            dimmer,
            _cancel_hit(self.width),
        ]

    def _companion_hits(self) -> list[Hit]:
        _qr_x, _qr_y, _side, brighter, dimmer = self._qr_layout()
        return [brighter, dimmer, _cancel_hit(self.width)]

    def _delete_hits(self) -> list[Hit]:
        y = self.height - 48
        return [
            Hit("erase", 8, y, self.width - 8, self.height - 6),
            _cancel_hit(self.width),
        ]


def _cancel_hit(width: int) -> Hit:
    return Hit("cancel", width - 8 - 112, 4, width - 8, 32)


def _draw_cancel(fb: FrameBuffer, width: int, *, held: bool, label: str = "Cancel") -> None:
    box = _cancel_hit(width)
    _button(fb, box, label, held=held)


def _icon_button(fb: FrameBuffer, item: Hit, kind: str, *, held: bool) -> None:
    _button(fb, item, "", held=held)
    ink = COLOR_BG if held else COLOR_FG
    cx, cy = item.center()
    if kind == "brighter":
        _draw_sun(fb.draw, cx, cy, ink, rays=True)
    else:
        _draw_sun(fb.draw, cx, cy, ink, rays=False)


def _draw_sun(draw, cx: int, cy: int, color: tuple[int, int, int], *, rays: bool) -> None:
    radius = 5 if rays else 4
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=color, width=2)
    if not rays:
        return
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
        draw.line((cx + dx * 8, cy + dy * 8, cx + dx * 11, cy + dy * 11), fill=color, width=2)


def _button_frame(fb: FrameBuffer, item: Hit, *, held: bool, danger: bool = False) -> None:
    outline = COLOR_DANGER if danger and not held else (COLOR_FG if held else COLOR_ACCENT)
    fb.draw.rounded_rectangle(
        (item.x0, item.y0, item.x1 - 1, item.y1 - 1),
        radius=8,
        fill=COLOR_ACCENT if held else (24, 24, 24),
        outline=outline,
        width=2,
    )


def _button(
    fb: FrameBuffer,
    item: Hit,
    label: str,
    *,
    held: bool,
    danger: bool = False,
) -> None:
    _button_frame(fb, item, held=held, danger=danger)
    ink = COLOR_BG if held else (COLOR_DANGER if danger else COLOR_FG)
    draw_text(fb, *item.center(), label, size=16, color=ink, anchor="mm")


def _draw_arrow(draw, cx: int, cy: int, color: tuple[int, int, int], *, left: bool) -> None:
    s = -1 if left else 1
    draw.line((cx - 7 * s, cy, cx + 5 * s, cy), fill=color, width=2)
    draw.line((cx + 5 * s, cy, cx - 1 * s, cy - 6), fill=color, width=2)
    draw.line((cx + 5 * s, cy, cx - 1 * s, cy + 6), fill=color, width=2)


def _nav_button(fb: FrameBuffer, item: Hit, *, held: bool) -> None:
    """Prev with a left arrow before the word, Next with a right arrow after."""
    _button_frame(fb, item, held=held)
    ink = COLOR_BG if held else COLOR_FG
    prev = item.id == "prev"
    label = "Prev" if prev else "Next"
    arrow_w = 14
    gap = 8
    text_w = _width(label, 16)
    cx, cy = item.center()
    x0 = cx - (arrow_w + gap + text_w) // 2
    if prev:
        _draw_arrow(fb.draw, x0 + arrow_w // 2, cy, ink, left=True)
        draw_text(fb, x0 + arrow_w + gap, cy, label, size=16, color=ink, anchor="lm")
    else:
        draw_text(fb, x0, cy, label, size=16, color=ink, anchor="lm")
        _draw_arrow(fb.draw, x0 + text_w + gap + arrow_w // 2, cy, ink, left=False)


def _fit(text: str, px: int, size: int) -> str:
    if _width(text, size) <= px:
        return text
    trimmed = text
    while trimmed and _width(trimmed + "...", size) > px:
        trimmed = trimmed[:-1]
    return (trimmed + "...") if trimmed else ""


def _width(text: str, size: int) -> int:
    left, _top, right, _bottom = text_bbox(text, size=size)
    return right - left


def _wrap(text: str, px: int, size: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if _width(candidate, size) <= px or not line:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _address_size(text: str, limit: int) -> int:
    for size in (14, 13, 12, 11):
        if _width(text, size) <= limit:
            return size
    return 11

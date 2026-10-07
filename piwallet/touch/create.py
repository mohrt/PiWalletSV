"""Touch create-wallet flow.

Word count, network, path, then random, photo, or dice. Phrase pages,
shuffled-word confirm, name, then ``Vault.add_wallet``. Same vault
record the joystick flow writes.
"""

from __future__ import annotations

import secrets
import time

from piwallet.bonnet.companion_pairing import pairing_pw1_lines
from piwallet.bonnet.entropy_camera import EntropyDualStreamCamera
from piwallet.camera_lcd import paste_cover, rgb888_thumbnail
from piwallet.core import derivation as deriv
from piwallet.core.mnemonic import (
    BIP39_WORDLIST,
    MIN_DICE_ROLLS,
    generate,
    mnemonic_from_camera_jpeg,
    mnemonic_from_dice_rolls,
)
from piwallet.core.mnemonic import MnemonicError
from piwallet.touch.ui import AlphabetKeyboard, Hit, IconGrid, _draw_delete_mark
from piwallet.core.vault import Vault, VaultError, WalletRecord, WrongPinError
from piwallet.touch.input import Tap
from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DANGER,
    COLOR_DIM,
    COLOR_FG,
    COLOR_OK,
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

_RNG = secrets.SystemRandom()
_WORDS_PER_PAGE = 12
_PIN_LENGTH = 6
_COUNT_HELP = (
    "12 words uses 128 bits of randomness. "
    "It is the shorter backup and the usual choice.\n"
    "24 words uses 256 bits of randomness. "
    "It is the longer backup.\n"
    "Both make the same kind of key. "
    "More words add randomness, not a stronger key."
)
_NETWORK_HELP = (
    "Mainnet holds real BSV. Use this when the coins should have value.\n"
    "Testnet holds coins with no value. Developers use it to build and test "
    "without spending real BSV.\n"
    "A testnet wallet cannot pay a mainnet address. "
    "Choose mainnet unless you are developing."
)
_PHRASE_HELP = (
    "These words are the only backup of this wallet. "
    "Keep them in a safe place. "
    "Printable seed phrase sheets are at piwalletsv.com."
)
_PHRASE_ROW_H = 32
_ENTROPY_HELP = (
    "Random uses the Pi's own random numbers. That is the usual choice.\n"
    "Photo mixes one picture from this camera with those numbers.\n"
    "Dice mixes die rolls with those numbers. "
    "12 words needs 48 rolls. 24 words needs 96.\n"
    "Photo and dice are added on top of the Pi's numbers. "
    "They do not replace them."
)
# Same frame size as the wallet's Show xpub screen on this panel.
_XPUB_CHUNK = 400
_QR_FRAME_S = 0.7
_ENTROPY_CHOICES: tuple[tuple[str, str], ...] = (
    ("csr", "Random (recommended)"),
    ("camera", "Photo + random"),
    ("dice", "Dice + random"),
)
_PATH_HELP = (
    "The path chooses which account this phrase opens. "
    "The usual BSV account is m/44'/236'/0'.\n"
    "BSV default keeps that path. That is what other wallets expect.\n"
    "Advanced changes the coin type or account. Use it to match a wallet "
    "you already have, or to keep a second account from the same words.\n"
    "If you change the path, write the new path on the same sheet as the seed phrase."
)
_SLOT_W = 28
_SLOT_H = 28
_SLOT_GAP = 8


def _bar_button(fb: FrameBuffer, x0: int, y0: int, x1: int, y1: int, label: str) -> None:
    fb.draw.rounded_rectangle(
        (x0, y0, x1 - 1, y1 - 1),
        radius=8,
        fill=(24, 24, 24),
        outline=COLOR_ACCENT,
        width=2,
    )
    draw_text(fb, (x0 + x1) // 2, (y0 + y1) // 2, label, size=16, color=COLOR_FG, anchor="mm")


def _draw_help(fb: FrameBuffer, y: int, text: str, width: int) -> None:
    """Wrap help copy under a row of choice buttons."""
    size = 15
    line_h = 20
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            left, _top, right, _bottom = text_bbox(candidate, size=size)
            if right - left <= width or not line:
                line = candidate
                continue
            draw_text(fb, 16, y, line, size=size, color=COLOR_DIM)
            y += line_h
            line = word
        if line:
            draw_text(fb, 16, y, line, size=size, color=COLOR_DIM)
            y += line_h
        y += 8


def _confirm_pool(target: str) -> list[str]:
    decoys = [w for w in BIP39_WORDLIST if w != target]
    pool = _RNG.sample(decoys, 6)
    pool.append(target)
    _RNG.shuffle(pool)
    return pool


class PinPad:
    """Six-digit PIN. ``result`` is set when OK is released on 6 digits."""

    def __init__(self, width: int, height: int, *, title: str, masked: bool = False) -> None:
        keys = tuple((d, d) for d in "123456789") + (("del", ""), ("0", "0"), ("ok", "OK"))
        self.grid = IconGrid(width, height - 24, keys, title=title, show_icons=False, top=88)
        self.masked = masked
        self.digits = ""
        self.result: str | None = None
        self.message = ""
        self.message_error = True
        self.quiet = 0

    def on_tap(self, tap: Tap) -> None:
        key = self.grid.on_tap(tap)
        if key is None:
            return
        if key == "del":
            self.digits = self.digits[:-1]
            self.message = ""
        elif key == "ok":
            if len(self.digits) == _PIN_LENGTH:
                self.result = self.digits
                self.message = ""
            else:
                self.result = None
                self.message = "Enter all 6 digits"
                self.message_error = True
        elif len(self.digits) < _PIN_LENGTH:
            self.digits += key
            self.message = ""

    def slot_boxes(self) -> list[tuple[int, int, int, int]]:
        row = _PIN_LENGTH * _SLOT_W + (_PIN_LENGTH - 1) * _SLOT_GAP
        x0 = (self.grid.width - row) // 2
        y0 = 42
        return [
            (x0 + i * (_SLOT_W + _SLOT_GAP), y0, x0 + i * (_SLOT_W + _SLOT_GAP) + _SLOT_W, y0 + _SLOT_H)
            for i in range(_PIN_LENGTH)
        ]

    def draw(self, fb: FrameBuffer) -> None:
        self.grid.status = ""
        self.grid.draw(fb)
        delete = self.grid.hit("del")
        held = self.grid.down == "del"
        _draw_delete_mark(
            fb.draw,
            *delete.center(),
            COLOR_BG if held else COLOR_FG,
        )
        if self.message:
            draw_text(
                fb,
                self.grid.width // 2,
                72,
                self.message,
                size=14,
                color=COLOR_DANGER if self.message_error else COLOR_OK,
                anchor="mt",
            )
        for i, (x0, y0, x1, y1) in enumerate(self.slot_boxes()):
            filled = i < len(self.digits)
            cursor = i == len(self.digits)
            outline = COLOR_ACCENT if cursor or filled else COLOR_DIM
            fb.draw.rounded_rectangle((x0, y0, x1, y1), radius=4, outline=outline, width=2)
            if filled:
                draw_text(
                    fb,
                    (x0 + x1) // 2,
                    (y0 + y1) // 2,
                    "*" if self.masked else self.digits[i],
                    size=16,
                    color=COLOR_FG,
                    anchor="mm",
                )


class PathEditor:
    """Coin type and account, matching the Zero custom HD path screen."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.coin_type = deriv.BSV_COIN_TYPE
        self.account_index = deriv.DEFAULT_ACCOUNT_INDEX
        self.down: str | None = None

    def on_tap(self, tap: Tap) -> str | None:
        hit = self._at(tap.x, tap.y)
        if tap.pressed:
            self.down = hit
            return None
        chosen = self.down
        self.down = None
        if chosen is None or chosen != hit:
            return None
        if chosen == "coin-":
            self.coin_type = max(0, self.coin_type - 1)
        elif chosen == "coin+":
            self.coin_type = min(999, self.coin_type + 1)
        elif chosen == "acct-":
            self.account_index = max(0, self.account_index - 1)
        elif chosen == "acct+":
            self.account_index = min(999, self.account_index + 1)
        elif chosen in ("back", "ok"):
            return chosen
        return None

    def _at(self, x: int, y: int) -> str | None:
        for name, box in self._boxes():
            x0, y0, x1, y1 = box
            if x0 <= x < x1 and y0 <= y < y1:
                return name
        return None

    def _boxes(self) -> list[tuple[str, tuple[int, int, int, int]]]:
        rows = (("coin-", "coin+"), ("acct-", "acct+"))
        boxes: list[tuple[str, tuple[int, int, int, int]]] = []
        for i, (minus, plus) in enumerate(rows):
            y0 = 70 + i * 70
            boxes.append((minus, (16, y0, 88, y0 + 48)))
            boxes.append((plus, (self.width - 88, y0, self.width - 16, y0 + 48)))
        mid = self.width // 2
        y = self.height - 48
        boxes.append(("back", (4, y, mid - 4, self.height - 6)))
        boxes.append(("ok", (mid + 4, y, self.width - 4, self.height - 6)))
        return boxes

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        draw_text(fb, 12, 8, "Custom path", size=18, color=COLOR_FG)
        draw_text(
            fb,
            self.width // 2,
            40,
            deriv.account_path(self.coin_type, self.account_index),
            size=16,
            color=COLOR_ACCENT,
            anchor="mt",
        )
        labels = {0: ("Coin type", str(self.coin_type)), 1: ("Account", str(self.account_index))}
        for i, (minus, plus) in enumerate((("coin-", "coin+"), ("acct-", "acct+"))):
            title, value = labels[i]
            y0 = 70 + i * 70
            draw_text(fb, self.width // 2, y0 - 2, title, size=14, color=COLOR_DIM, anchor="mt")
            self._button(fb, minus, 16, y0, 88, y0 + 48, "-")
            self._button(fb, plus, self.width - 88, y0, self.width - 16, y0 + 48, "+")
            draw_text(fb, self.width // 2, y0 + 24, value, size=22, color=COLOR_FG, anchor="mm")
        mid = self.width // 2
        y = self.height - 48
        self._button(fb, "back", 4, y, mid - 4, self.height - 6, "Back")
        self._button(fb, "ok", mid + 4, y, self.width - 4, self.height - 6, "OK")

    def _button(self, fb: FrameBuffer, name: str, x0: int, y0: int, x1: int, y1: int, label: str) -> None:
        held = name == self.down
        fb.draw.rounded_rectangle(
            (x0, y0, x1, y1),
            radius=8,
            fill=COLOR_ACCENT if held else (24, 24, 24),
            outline=COLOR_FG if held else COLOR_ACCENT,
            width=3 if held else 2,
        )
        draw_text(
            fb,
            (x0 + x1) // 2,
            (y0 + y1) // 2,
            label,
            size=18,
            color=COLOR_BG if held else COLOR_FG,
            anchor="mm",
        )


class CreateFlow:
    """One new-wallet attempt. ``done`` is set on save or cancel."""

    def __init__(
        self,
        width: int,
        height: int,
        vault: Vault,
        pin: str,
        *,
        camera_rotation: int = 0,
        camera_cls: type = EntropyDualStreamCamera,
    ) -> None:
        self.width = width
        self.height = height
        self.vault = vault
        self.pin = pin
        self.camera_rotation = camera_rotation
        self._camera_cls = camera_cls
        self.phase = "count"
        self.done = False
        self.cancelled = False
        self.error: str | None = None
        self.label: str | None = None
        self._words: list[str] = []
        self._page = 0
        self._index = 0
        self._word_count = 0
        self._network: deriv.Network = deriv.NETWORK_MAIN
        self._coin_type = deriv.BSV_COIN_TYPE
        self._account = deriv.DEFAULT_ACCOUNT_INDEX
        self._count = IconGrid(
            width,
            height,
            (("12", "12 words"), ("24", "24 words"), ("cancel", "Cancel")),
            title="New wallet",
            show_icons=False,
        )
        self._network_grid = IconGrid(
            width,
            height,
            (("main", "Mainnet"), ("test", "Testnet"), ("cancel", "Cancel")),
            title="Network",
            show_icons=False,
        )
        self._path_grid = IconGrid(
            width,
            height,
            (("default", "BSV default"), ("advanced", "Advanced"), ("cancel", "Cancel")),
            title="HD path",
            show_icons=False,
        )
        self._editor = PathEditor(width, height)
        self._confirm: IconGrid | None = None
        self._confirm_error = ""
        self._name: AlphabetKeyboard | None = None
        self._down: str | None = None
        self._rolls: list[int] = []
        self._photo = None
        self._photo_error = ""
        self._photo_thumb = None
        self._jpeg: bytes | None = None
        self._preview_at = 0.0
        self._saved: WalletRecord | None = None
        self._frames: list[str] = []
        self._frame = 0
        self._frame_at = 0.0
        self._qr_bg = increase_qr_background(increase_qr_background(DEFAULT_QR_BACKGROUND))
        self._pair_error = ""

    def on_tap(self, tap: Tap) -> None:
        if self.done:
            return
        if self.phase == "count":
            choice = self._count.on_tap(tap)
            if choice == "cancel":
                self._cancel()
            elif choice in ("12", "24"):
                self._word_count = int(choice)
                self.phase = "network"
        elif self.phase == "network":
            choice = self._network_grid.on_tap(tap)
            if choice == "cancel":
                self._cancel()
            elif choice in ("main", "test"):
                self._network = choice
                self.phase = "path"
        elif self.phase == "path":
            choice = self._path_grid.on_tap(tap)
            if choice == "cancel":
                self._cancel()
            elif choice == "default":
                self._coin_type = deriv.BSV_COIN_TYPE
                self._account = deriv.DEFAULT_ACCOUNT_INDEX
                self.phase = "entropy"
            elif choice == "advanced":
                self._editor = PathEditor(self.width, self.height)
                self.phase = "custom"
        elif self.phase == "custom":
            choice = self._editor.on_tap(tap)
            if choice == "back":
                self.phase = "path"
            elif choice == "ok":
                self._coin_type = self._editor.coin_type
                self._account = self._editor.account_index
                self.phase = "entropy"
        elif self.phase == "entropy":
            self._on_entropy(tap)
        elif self.phase == "photo":
            self._on_photo(tap)
        elif self.phase == "photo_ok":
            self._on_photo_ok(tap)
        elif self.phase == "dice":
            self._on_dice(tap)
        elif self.phase == "show":
            self._on_show(tap)
        elif self.phase == "confirm":
            self._on_confirm(tap)
        elif self.phase == "name" and self._name is not None:
            self._name.on_tap(tap)
            if self._name.done:
                if self._name.result:
                    self._save(self._name.result)
                else:
                    self._cancel()
        elif self.phase == "pair":
            self._on_pair(tap)
        elif self.phase == "qr":
            self._on_qr(tap)

    def _on_show(self, tap: Tap) -> None:
        if self._header_cancel(tap):
            self._cancel()
            return
        action = self._bar_hit(tap)
        if action == "back":
            if self._page > 0:
                self._page -= 1
            else:
                self._cancel()
        elif action == "next":
            last = (len(self._words) - 1) // _WORDS_PER_PAGE
            if self._page < last:
                self._page += 1
            else:
                self._index = 0
                self._confirm_error = ""
                self._new_pool()
                self.phase = "confirm"

    def _on_confirm(self, tap: Tap) -> None:
        assert self._confirm is not None
        picked = self._confirm.on_tap(tap)
        if picked is None:
            return
        if picked == "cancel":
            self._cancel()
            return
        if picked != self._words[self._index]:
            self._confirm_error = "Wrong word. Try again."
            self._new_pool()
            return
        self._confirm_error = ""
        self._index += 1
        if self._index >= len(self._words):
            self._name = AlphabetKeyboard(self.width, self.height, mode="name", title="Wallet name")
            self.phase = "name"
            return
        self._new_pool()

    def _new_pool(self) -> None:
        target = self._words[self._index]
        actions = tuple((word, word) for word in _confirm_pool(target))
        actions = actions + (("cancel", "Cancel"),)
        self._confirm = IconGrid(
            self.width,
            self.height,
            actions,
            title=f"Word {self._index + 1} of {len(self._words)}",
            show_icons=False,
        )

    def _save(self, label: str) -> None:
        name = label.strip()
        if not name:
            return
        try:
            existing = self.vault.list_wallets()
            if existing:
                self.vault.get_account_xpub(self.pin, existing[0].id)
            rec = self.vault.add_wallet(
                self.pin,
                " ".join(self._words),
                name,
                coin_type=self._coin_type,
                account_index=self._account,
                network=self._network,
            )
        except WrongPinError as exc:
            self.error = str(exc)
            self.done = True
            return
        except VaultError as exc:
            self.error = str(exc)
            self.done = True
            return
        self._words = []
        self.label = rec.label
        self._saved = rec
        self.phase = "pair"

    def _on_pair(self, tap: Tap) -> None:
        choice = self._release(tap, self._pair_hits())
        if choice == "skip":
            self.done = True
        elif choice == "show":
            self._open_qr()

    def _open_qr(self) -> None:
        wallet = self._saved
        if wallet is None:
            self.done = True
            return
        try:
            frames = pairing_pw1_lines(self.vault, self.pin, wallet, chunk_chars=_XPUB_CHUNK)
        except VaultError as exc:
            self._pair_error = str(exc)[:80]
            return
        if not frames:
            self._pair_error = "No QR data."
            return
        self._frames = frames
        self._frame = 0
        self._frame_at = time.monotonic()
        self._pair_error = ""
        self.phase = "qr"

    def _on_qr(self, tap: Tap) -> None:
        choice = self._release(tap, self._qr_hits())
        if choice == "cancel":
            self._frames = []
            self.done = True
        elif choice == "brighter":
            self._qr_bg = increase_qr_background(self._qr_bg)
            self._frame = 0
            self._frame_at = time.monotonic()
        elif choice == "dimmer":
            self._qr_bg = decrease_qr_background(self._qr_bg)
            self._frame = 0
            self._frame_at = time.monotonic()

    def _advance_qr(self) -> bool:
        if self.phase != "qr" or len(self._frames) < 2:
            return False
        now = time.monotonic()
        if now < self._frame_at + _QR_FRAME_S:
            return False
        self._frame = (self._frame + 1) % len(self._frames)
        self._frame_at = now
        return True

    def _cancel(self) -> None:
        self._close_photo()
        self.cancelled = True
        self.done = True

    def tick(self) -> bool:
        """Repaint when the photo preview or the pairing QR changes."""
        changed = self._advance_qr()
        if self.phase != "photo" or self._photo_error:
            return changed
        if self._photo is None:
            try:
                cam = self._camera_cls(rotation_degrees=self.camera_rotation)
                cam.open()
            except Exception as exc:
                self._photo_error = str(exc)[:80]
                return True
            self._photo = cam
            return True
        now = time.monotonic()
        if now < self._preview_at + 0.28:
            return changed
        self._preview_at = now
        try:
            self._photo_thumb = rgb888_thumbnail(self._photo.read_preview_rgb(), max_edge=320)
        except Exception as exc:
            self._photo_error = str(exc)[:80]
        return True

    def _on_entropy(self, tap: Tap) -> None:
        choice = self._release(tap, self._entropy_hits())
        if choice is None:
            return
        if choice == "cancel":
            self._cancel()
            return
        if choice == "csr":
            self._show_phrase(generate(self._word_count))
            return
        if choice == "camera":
            self._photo_error = ""
            self._photo_thumb = None
            self._jpeg = None
            self.phase = "photo"
            return
        if choice == "dice":
            self._rolls = []
            self.phase = "dice"

    def _on_photo(self, tap: Tap) -> None:
        choice = self._release(tap, self._photo_hits())
        if choice is None:
            return
        if choice == "cancel":
            self._close_photo()
            self.phase = "entropy"
            return
        if choice != "capture" or self._photo is None:
            return
        try:
            self._jpeg = self._photo.capture_entropy_jpeg()
            self._photo_thumb = None
        except Exception as exc:
            self._photo_error = str(exc)[:80]
            return
        self._close_photo()
        self.phase = "photo_ok"

    def _on_photo_ok(self, tap: Tap) -> None:
        choice = self._release(tap, self._photo_ok_hits())
        if choice is None:
            return
        if choice == "retake":
            self._jpeg = None
            self._photo_error = ""
            self.phase = "photo"
            return
        if choice == "use" and self._jpeg:
            try:
                phrase = mnemonic_from_camera_jpeg(self._jpeg, self._word_count)
            except MnemonicError as exc:
                self._photo_error = str(exc)[:80]
                self.phase = "photo"
                return
            self._jpeg = None
            self._show_phrase(phrase)

    def _on_dice(self, tap: Tap) -> None:
        choice = self._release(tap, self._dice_hits())
        if choice is None:
            return
        if choice == "cancel":
            self.phase = "entropy"
            return
        if choice == "undo":
            if self._rolls:
                self._rolls.pop()
            return
        if choice.startswith("face:"):
            self._rolls.append(int(choice.split(":", 1)[1]))
            if len(self._rolls) >= MIN_DICE_ROLLS[self._word_count]:
                try:
                    phrase = mnemonic_from_dice_rolls(self._rolls, self._word_count)
                except MnemonicError as exc:
                    self.error = str(exc)
                    self.done = True
                    return
                self._rolls = []
                self._show_phrase(phrase)

    def _show_phrase(self, phrase: str) -> None:
        self._close_photo()
        self._words = phrase.split()
        self._page = 0
        self.phase = "show"

    def _close_photo(self) -> None:
        cam = self._photo
        self._photo = None
        if cam is not None:
            cam.close()

    def _entropy_hits(self) -> list[Hit]:
        hits = [Hit("cancel", self.width - 8 - 112, 4, self.width - 8, 32)]
        y = 48
        for action_id, _label in _ENTROPY_CHOICES:
            hits.append(Hit(action_id, 8, y, self.width - 8, y + 56))
            y += 64
        return hits

    def _photo_hits(self) -> list[Hit]:
        return [
            Hit("cancel", self.width - 8 - 112, 4, self.width - 8, 32),
            Hit("capture", 8, self.height - 48, self.width - 8, self.height - 6),
        ]

    def _photo_ok_hits(self) -> list[Hit]:
        mid = self.width // 2
        y = self.height - 48
        return [
            Hit("retake", 4, y, mid - 4, self.height - 6),
            Hit("use", mid + 4, y, self.width - 4, self.height - 6),
        ]

    def _dice_hits(self) -> list[Hit]:
        hits = [Hit("cancel", self.width - 8 - 112, 4, self.width - 8, 32)]
        gap = 6
        side = min(52, (self.width - 16 - gap * 5) // 6)
        row = 6 * side + 5 * gap
        x = (self.width - row) // 2
        y0 = 62
        for face in range(1, 7):
            hits.append(Hit(f"face:{face}", x, y0, x + side, y0 + side))
            x += side + gap
        hits.append(Hit("undo", 8, self.height - 48, self.width - 8, self.height - 6))
        return hits

    def _release(self, tap: Tap, hits: list[Hit]) -> str | None:
        hit = None
        for item in hits:
            if item.contains(tap.x, tap.y):
                hit = item.id
                break
        if tap.pressed:
            self._down = hit
            return None
        chosen = self._down
        self._down = None
        if chosen is not None and chosen == hit:
            return chosen
        return None

    def _header_cancel(self, tap: Tap) -> bool:
        if tap.pressed:
            return False
        x0, y0, x1, y1 = self.width - 120, 4, self.width - 8, 32
        return x0 <= tap.x < x1 and y0 <= tap.y < y1

    def _bar_hit(self, tap: Tap) -> str | None:
        if tap.pressed:
            return None
        mid = self.width // 2
        if tap.y < self.height - 52:
            return None
        if tap.x < mid:
            return None if self._page == 0 else "back"
        return "next"

    def draw(self, fb: FrameBuffer) -> None:
        if self.phase == "count":
            self._count.draw(fb)
            _draw_help(fb, self._count.hit("12").y1 + 16, _COUNT_HELP, self.width - 32)
            return
        if self.phase == "network":
            self._network_grid.draw(fb)
            _draw_help(fb, self._network_grid.hit("main").y1 + 16, _NETWORK_HELP, self.width - 32)
            return
        if self.phase == "path":
            self._path_grid.draw(fb)
            _draw_help(fb, self._path_grid.hit("default").y1 + 16, _PATH_HELP, self.width - 32)
            return
        if self.phase == "custom":
            self._editor.draw(fb)
            return
        if self.phase == "entropy":
            self._draw_entropy(fb)
            return
        if self.phase == "photo":
            self._draw_photo(fb)
            return
        if self.phase == "photo_ok":
            self._draw_photo_ok(fb)
            return
        if self.phase == "dice":
            self._draw_dice(fb)
            return
        if self.phase == "show":
            self._draw_show(fb)
            return
        if self.phase == "confirm" and self._confirm is not None:
            self._confirm.draw(fb)
            if self._confirm_error:
                bottom = max(item.y1 for item in self._confirm._hits if item.id != "cancel")
                draw_text(fb, 16, bottom + 16, self._confirm_error, size=16, color=COLOR_DANGER)
            return
        if self.phase == "name" and self._name is not None:
            self._name.draw(fb)
            return
        if self.phase == "pair":
            self._draw_pair(fb)
            return
        if self.phase == "qr":
            self._draw_qr(fb)
            return

    def _pair_hits(self) -> list[Hit]:
        return [
            Hit("show", 8, 150, self.width - 8, 214),
            Hit("skip", 8, 230, self.width - 8, 294),
        ]

    def _qr_hits(self) -> list[Hit]:
        _x, _y, _side, brighter, dimmer = self._qr_layout()
        return [brighter, dimmer, Hit("cancel", self.width - 8 - 112, 4, self.width - 8, 32)]

    def _qr_layout(self) -> tuple[int, int, int, Hit, Hit]:
        btn = 44
        gap = 8
        btn_x1 = self.width - 8
        btn_x0 = btn_x1 - btn
        side = max(80, btn_x0 - gap - 12)
        qr_x = 12
        qr_y = 44
        pair = btn * 2 + gap
        top = qr_y + max(0, (side - pair) // 2)
        brighter = Hit("brighter", btn_x0, top, btn_x1, top + btn)
        dimmer = Hit("dimmer", btn_x0, top + btn + gap, btn_x1, top + pair)
        return qr_x, qr_y, side, brighter, dimmer

    def _draw_pair(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        label = self.label or "wallet"
        draw_text(fb, 12, 8, "Pair this wallet?", size=18, color=COLOR_FG)
        y = 56
        for line in (
            f'"{label}" is saved.',
            "Show a QR the companion can scan,",
            "or skip and do it later.",
        ):
            draw_text(fb, 16, y, line, size=16, color=COLOR_DIM)
            y += 24
        if self._pair_error:
            draw_text(fb, 16, y, self._pair_error, size=15, color=COLOR_DANGER)
        labels = {"show": "Show companion QR", "skip": "Skip (do later)"}
        for item in self._pair_hits():
            held = item.id == self._down
            fb.draw.rounded_rectangle(
                (item.x0, item.y0, item.x1 - 1, item.y1 - 1),
                radius=8,
                fill=COLOR_ACCENT if held else (24, 24, 24),
                outline=COLOR_FG if held else COLOR_ACCENT,
                width=3 if held else 2,
            )
            draw_text(fb, *item.center(), labels[item.id], size=16, color=COLOR_BG if held else COLOR_FG, anchor="mm")

    def _draw_qr(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        count = len(self._frames)
        title = f"Xpub {self._frame + 1}/{count}" if count else "Xpub"
        draw_text(fb, 12, 8, title, size=18, color=COLOR_FG)
        for item in self._qr_hits():
            if item.id == "cancel":
                held = item.id == self._down
                fb.draw.rounded_rectangle(
                    (item.x0, item.y0, item.x1 - 1, item.y1 - 1),
                    radius=8,
                    fill=COLOR_ACCENT if held else (24, 24, 24),
                    outline=COLOR_FG if held else COLOR_ACCENT,
                    width=2,
                )
                draw_text(fb, *item.center(), "Done", size=16, color=COLOR_BG if held else COLOR_FG, anchor="mm")
                continue
            held = item.id == self._down
            fb.draw.rounded_rectangle(
                (item.x0, item.y0, item.x1 - 1, item.y1 - 1),
                radius=8,
                fill=COLOR_ACCENT if held else (24, 24, 24),
                outline=COLOR_FG if held else COLOR_ACCENT,
                width=2,
            )
            mark = "+" if item.id == "brighter" else "-"
            draw_text(fb, *item.center(), mark, size=18, color=COLOR_BG if held else COLOR_FG, anchor="mm")
        if not self._frames:
            return
        qr_x, qr_y, side, _bright, _dim = self._qr_layout()
        qr = render_qr(self._frames[self._frame], target_px=side, error="L", bg=qr_background_rgb(self._qr_bg))
        fb.image.paste(qr, (qr_x, qr_y))

    def _draw_show(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        start = self._page * _WORDS_PER_PAGE
        chunk = self._words[start : start + _WORDS_PER_PAGE]
        title = "Write these words down"
        cancel_x = self.width - 116
        draw_text(
            fb,
            12,
            8,
            title,
            size=_line_size(title, cancel_x - 12 - 12),
            color=COLOR_FG,
        )
        fb.draw.rounded_rectangle((cancel_x, 4, self.width - 8, 32), radius=8, outline=COLOR_ACCENT, width=2)
        draw_text(fb, self.width - 62, 18, "Cancel", size=16, color=COLOR_FG, anchor="mm")
        per_col = 6
        word_top = 56
        for i, word in enumerate(chunk):
            col = i // per_col
            row = i % per_col
            x = 16 + col * (self.width // 2)
            y = word_top + row * _PHRASE_ROW_H
            draw_text(fb, x, y, f"{start + i + 1}. {word}", size=16, color=COLOR_FG)
        help_y = word_top + per_col * _PHRASE_ROW_H + 8
        if help_y + 40 < self.height - 48:
            _draw_help(fb, help_y, _PHRASE_HELP, self.width - 32)
        mid = self.width // 2
        y = self.height - 48
        nxt = "Confirm" if start + _WORDS_PER_PAGE >= len(self._words) else "Next"
        if self._page == 0:
            _bar_button(fb, 4, y, self.width - 4, self.height - 6, nxt)
        else:
            _bar_button(fb, 4, y, mid - 4, self.height - 6, "Back")
            _bar_button(fb, mid + 4, y, self.width - 4, self.height - 6, nxt)

    def _draw_entropy(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        draw_text(fb, 12, 8, "Randomness", size=18, color=COLOR_FG)
        labels = dict(_ENTROPY_CHOICES)
        bottom = 48
        for item in self._entropy_hits():
            if item.id == "cancel":
                _choice(fb, item, "Cancel", held=self._down == "cancel")
                continue
            _choice(fb, item, labels[item.id], held=self._down == item.id)
            bottom = item.y1
        _draw_help(fb, bottom + 16, _ENTROPY_HELP, self.width - 32)

    def _draw_photo(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        draw_text(fb, 12, 8, "Photo", size=18, color=COLOR_FG)
        for item in self._photo_hits():
            label = "Cancel" if item.id == "cancel" else "Capture"
            _choice(fb, item, label, held=self._down == item.id)
        box = (8, 44, self.width - 8, self.height - 96)
        if self._photo_thumb is not None:
            paste_cover(fb.image, self._photo_thumb, box)
        else:
            fb.draw.rectangle(box, fill=(12, 12, 18))
            draw_text(
                fb,
                self.width // 2,
                (box[1] + box[3]) // 2,
                self._photo_error or "Opening camera...",
                size=16,
                color=COLOR_DANGER if self._photo_error else COLOR_DIM,
                anchor="mm",
            )
        draw_text(
            fb,
            self.width // 2,
            self.height - 64,
            "Mixed with the Pi's random numbers",
            size=14,
            color=COLOR_OK,
            anchor="mm",
        )

    def _draw_photo_ok(self, fb: FrameBuffer) -> None:
        from io import BytesIO

        from PIL import Image

        fb.clear(COLOR_BG)
        draw_text(fb, 12, 8, "Photo captured", size=18, color=COLOR_OK)
        box = (8, 44, self.width - 8, self.height - 96)
        if self._jpeg:
            with Image.open(BytesIO(self._jpeg)) as img:
                thumb = img.convert("RGB")
            paste_cover(fb.image, thumb, box)
        draw_text(
            fb,
            self.width // 2,
            self.height - 64,
            "Mixed with the Pi's random numbers",
            size=14,
            color=COLOR_OK,
            anchor="mm",
        )
        for item in self._photo_ok_hits():
            label = "Retake" if item.id == "retake" else "Use photo"
            _choice(fb, item, label, held=self._down == item.id)

    def _draw_dice(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        need = MIN_DICE_ROLLS[self._word_count]
        draw_text(fb, 12, 8, "Dice", size=18, color=COLOR_FG)
        for item in self._dice_hits():
            if item.id == "cancel":
                _choice(fb, item, "Cancel", held=self._down == "cancel")
            elif item.id == "undo":
                _choice(fb, item, "Undo", held=self._down == "undo")
            elif item.id.startswith("face:"):
                _draw_die(fb, item, int(item.id.split(":", 1)[1]), held=self._down == item.id)
        draw_text(
            fb,
            self.width // 2,
            46,
            f"{len(self._rolls)}/{need}",
            size=18,
            color=COLOR_FG,
            anchor="mm",
        )
        for index, x0, y0, x1, y1 in self._roll_boxes():
            if index >= len(self._rolls):
                continue
            size = 20 if (x1 - x0) >= 30 else 16
            draw_text(
                fb,
                (x0 + x1) // 2,
                (y0 + y1) // 2,
                str(self._rolls[index]),
                size=size,
                color=COLOR_FG,
                anchor="mm",
            )

    def _roll_boxes(self) -> list[tuple[int, int, int, int, int]]:
        """One slot per required roll, under the face and above the buttons."""
        need = MIN_DICE_ROLLS[self._word_count]
        cols = 8 if need <= 48 else 12
        rows = (need + cols - 1) // cols
        gap = 4 if cols <= 8 else 3
        left, right = 8, self.width - 8
        top, bottom = 118, self.height - 56
        cell_w = (right - left - gap * (cols - 1)) // cols
        cell_h = (bottom - top - gap * (rows - 1)) // rows
        side = max(12, min(cell_w, cell_h))
        grid_w = cols * side + gap * (cols - 1)
        grid_h = rows * side + gap * (rows - 1)
        x_origin = left + (right - left - grid_w) // 2
        y_origin = top + (bottom - top - grid_h) // 2
        boxes: list[tuple[int, int, int, int, int]] = []
        for index in range(need):
            col = index % cols
            row = index // cols
            x0 = x_origin + col * (side + gap)
            y0 = y_origin + row * (side + gap)
            boxes.append((index, x0, y0, x0 + side, y0 + side))
        return boxes


def _draw_die(fb: FrameBuffer, item: Hit, face: int, *, held: bool) -> None:
    """One face of a die. A tap records that face as the next roll."""
    ink = COLOR_BG if held else COLOR_FG
    fb.draw.rounded_rectangle(
        (item.x0, item.y0, item.x1 - 1, item.y1 - 1),
        radius=8,
        fill=COLOR_ACCENT if held else (24, 24, 24),
        outline=COLOR_FG if held else COLOR_ACCENT,
        width=2,
    )
    cx, cy = item.center()
    span = min(item.x1 - item.x0, item.y1 - item.y0)
    radius = max(2, span // 10)
    offset = span * 0.26
    spots = {
        1: ((0, 0),),
        2: ((-1, -1), (1, 1)),
        3: ((-1, -1), (0, 0), (1, 1)),
        4: ((-1, -1), (1, -1), (-1, 1), (1, 1)),
        5: ((-1, -1), (1, -1), (0, 0), (-1, 1), (1, 1)),
        6: ((-1, -1), (-1, 0), (-1, 1), (1, -1), (1, 0), (1, 1)),
    }
    for dx, dy in spots[face]:
        px = cx + dx * offset
        py = cy + dy * offset
        fb.draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=ink)


def _line_size(text: str, limit: int) -> int:
    """Largest size from 16 down that keeps ``text`` inside ``limit`` pixels."""
    size = 16
    while size > 11 and text_bbox(text, size=size)[2] - text_bbox(text, size=size)[0] > limit:
        size -= 1
    return size


def _choice(fb: FrameBuffer, item: Hit, label: str, *, held: bool) -> None:
    fb.draw.rounded_rectangle(
        (item.x0, item.y0, item.x1 - 1, item.y1 - 1),
        radius=8,
        fill=COLOR_ACCENT if held else (24, 24, 24),
        outline=COLOR_FG if held else COLOR_ACCENT,
        width=3 if held else 2,
    )
    draw_text(
        fb,
        *item.center(),
        label,
        size=16,
        color=COLOR_BG if held else COLOR_FG,
        anchor="mm",
    )

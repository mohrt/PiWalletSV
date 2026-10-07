"""Touch restore flow.

Same steps as the Zero: word count, network, HD path, then each
mnemonic word, a checksum review, and a name. One accepted word stays
on this flow until the phrase is saved or cancelled.
"""

from __future__ import annotations

from piwallet.core import derivation as deriv
from piwallet.core.mnemonic import MnemonicError, validate
from piwallet.core.vault import Vault, VaultError, WrongPinError
from piwallet.touch.create import (
    PathEditor,
    _COUNT_HELP,
    _NETWORK_HELP,
    _PATH_HELP,
    _bar_button,
    _draw_help,
)
from piwallet.touch.input import Tap
from piwallet.touch.ui import AlphabetKeyboard, Hit, IconGrid
from piwallet.ui.display import COLOR_BG, COLOR_DANGER, COLOR_FG, COLOR_OK, FrameBuffer
from piwallet.ui.widgets import draw_text


class RestoreFlow:
    """One restore attempt. ``done`` is set on save or cancel."""

    def __init__(self, width: int, height: int, vault: Vault, pin: str) -> None:
        self.width = width
        self.height = height
        self.vault = vault
        self.pin = pin
        self.phase = "count"
        self.done = False
        self.error: str | None = None
        self.label: str | None = None
        self._words: list[str] = []
        self._word_count = 0
        self._network: deriv.Network = deriv.NETWORK_MAIN
        self._coin_type = deriv.BSV_COIN_TYPE
        self._account = deriv.DEFAULT_ACCOUNT_INDEX
        self._edit_index: int | None = None
        self._down: str | None = None
        self._keyboard: AlphabetKeyboard | None = None
        self._count = IconGrid(
            width,
            height,
            (("12", "12 words"), ("24", "24 words"), ("cancel", "Cancel")),
            title="Restore",
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
                self._begin_words(deriv.BSV_COIN_TYPE, deriv.DEFAULT_ACCOUNT_INDEX)
            elif choice == "advanced":
                self._editor = PathEditor(self.width, self.height)
                self.phase = "custom"
        elif self.phase == "custom":
            choice = self._editor.on_tap(tap)
            if choice == "back":
                self.phase = "path"
            elif choice == "ok":
                self._begin_words(self._editor.coin_type, self._editor.account_index)
        elif self.phase in ("word", "edit") and self._keyboard is not None:
            self._on_keyboard(tap)
        elif self.phase == "review":
            self._on_review(tap)
        elif self.phase == "name" and self._keyboard is not None:
            self._keyboard.on_tap(tap)
            if self._keyboard.done:
                if self._keyboard.result:
                    self._save(self._keyboard.result)
                else:
                    self.phase = "review"
                    self._keyboard = None

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
        if self.phase in ("word", "edit", "name") and self._keyboard is not None:
            self._keyboard.draw(fb)
            if self.phase != "name":
                self._draw_chosen(fb)
            return
        if self.phase == "review":
            self._draw_review(fb)

    def _on_keyboard(self, tap: Tap) -> None:
        assert self._keyboard is not None
        self._keyboard.on_tap(tap)
        if not self._keyboard.done:
            return
        if self._keyboard.went_back:
            self._step_back()
            return
        word = self._keyboard.result
        if self.phase == "edit":
            if word is not None and self._edit_index is not None:
                self._words[self._edit_index] = word
            self._edit_index = None
            self._keyboard = None
            self.phase = "review"
            return
        if word is None:
            self._cancel()
            return
        self._words.append(word)
        if len(self._words) < self._word_count:
            self._open_word()
            return
        self._keyboard = None
        self.phase = "review"

    def _on_review(self, tap: Tap) -> None:
        choice = self._release(tap)
        if choice is None:
            return
        if choice == "cancel":
            self._cancel()
            return
        if choice == "save":
            if self.checksum_ok():
                self._open_name()
            return
        if choice.startswith("word:"):
            index = int(choice.split(":", 1)[1])
            self._edit_index = index
            self._keyboard = AlphabetKeyboard(
                self.width,
                self.height,
                mode="word",
                title=f"Word {index + 1} of {self._word_count}",
            )
            self._keyboard.text = self._words[index]
            self.phase = "edit"

    def checksum_ok(self) -> bool:
        if len(self._words) != self._word_count:
            return False
        try:
            validate(" ".join(self._words))
        except MnemonicError:
            return False
        return True

    def _begin_words(self, coin_type: int, account: int) -> None:
        self._coin_type = coin_type
        self._account = account
        self._words = []
        self._open_word()

    def _open_word(self) -> None:
        n = len(self._words) + 1
        self._keyboard = AlphabetKeyboard(
            self.width,
            self.height,
            mode="word",
            title=f"Word {n} of {self._word_count}",
            word_back=True,
        )
        self.phase = "word"

    def _step_back(self) -> None:
        if self._words:
            self._words.pop()
            self._open_word()
            return
        self._keyboard = None
        self.phase = "path"

    def _open_name(self) -> None:
        board = AlphabetKeyboard(self.width, self.height, mode="name", title="Wallet name")
        board.text = self._default_label()
        self._keyboard = board
        self.phase = "name"

    def _default_label(self) -> str:
        existing = {wallet.label for wallet in self.vault.list_wallets()}
        n = 1
        while f"restored-{n}" in existing:
            n += 1
        return f"restored-{n}"

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
        self.label = rec.label
        self._words = []
        self._keyboard = None
        self.done = True

    def _cancel(self) -> None:
        self._words = []
        self._keyboard = None
        self.done = True

    def _review_hits(self) -> list[Hit]:
        hits = [Hit("cancel", self.width - 8 - 112, 4, self.width - 8, 32)]
        rows = max(1, self._word_count // 2)
        top = 48
        bottom = self.height - (56 if self.checksum_ok() else 40)
        row_h = max(16, (bottom - top) // rows)
        col_w = self.width // 2
        for index in range(len(self._words)):
            col = index // rows
            row = index % rows
            x0 = 8 + col * col_w
            y0 = top + row * row_h
            hits.append(Hit(f"word:{index}", x0, y0, x0 + col_w - 8, y0 + row_h - 2))
        if self.checksum_ok():
            hits.append(Hit("save", 8, self.height - 48, self.width - 8, self.height - 6))
        return hits

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
        for item in self._review_hits():
            if item.contains(x, y):
                return item.id
        return None

    def _draw_chosen(self, fb: FrameBuffer) -> None:
        if not self._words or self._keyboard is None:
            return
        top = self._keyboard.hit("ok").y1 + 8
        if top >= self.height - 14:
            return
        per_col = max(1, self._word_count // 2)
        row_h = min(22, max(14, (self.height - top - 6) // per_col))
        size = 14 if row_h >= 18 else 12
        col_w = self.width // 2
        for index, word in enumerate(self._words):
            col = index // per_col
            row = index % per_col
            y = top + row * row_h
            if y > self.height - size:
                break
            draw_text(fb, 12 + col * col_w, y, f"{index + 1}. {word}", size=size, color=COLOR_FG)

    def _draw_review(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        ok = self.checksum_ok()
        draw_text(
            fb,
            12,
            8,
            "Phrase OK" if ok else "Checksum invalid",
            size=18,
            color=COLOR_OK if ok else COLOR_DANGER,
        )
        cancel = next(item for item in self._review_hits() if item.id == "cancel")
        _bar_button(fb, cancel.x0, cancel.y0, cancel.x1, cancel.y1, "Cancel")
        for item in self._review_hits():
            if not item.id.startswith("word:"):
                continue
            index = int(item.id.split(":", 1)[1])
            draw_text(
                fb,
                item.x0,
                item.y0,
                f"{index + 1}. {self._words[index]}",
                size=15,
                color=COLOR_FG,
            )
        if ok:
            save = next(item for item in self._review_hits() if item.id == "save")
            _bar_button(fb, save.x0, save.y0, save.x1, save.y1, "Save")
        else:
            draw_text(fb, 16, self.height - 28, "Tap a word to fix it.", size=15, color=COLOR_DANGER)

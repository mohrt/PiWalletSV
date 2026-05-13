"""Small reusable ListView-backed chooser screens for bonnet flows."""

from __future__ import annotations

from dataclasses import dataclass, field

from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.widgets import ListItem, ListView


@dataclass
class WordCountChooser:
    """Pick 12 vs 24 words."""

    done: bool = False
    result: int | None = None
    _list: ListView = field(init=False)

    def __post_init__(self) -> None:
        self._list = ListView(
            items=[
                ListItem(label="12 words", value=12),
                ListItem(label="24 words", value=24),
            ],
            title="Phrase length",
        )

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        if event.button == Button.B and event.kind == EventKind.LONG:
            self.done = True
            self.result = None
            return
        self._list.on_event(event)
        if self._list.confirmed is not None:
            self.done = True
            self.result = int(self._list.confirmed)  # type: ignore[arg-type]

    def draw(self, fb: FrameBuffer) -> None:
        self._list.draw(fb)


@dataclass
class EntropySourceChooser:
    """How to gather entropy for a new mnemonic."""

    done: bool = False
    result: str | None = None  # "csr" | "camera" | "dice"
    _list: ListView = field(init=False)

    def __post_init__(self) -> None:
        self._list = ListView(
            items=[
                ListItem(label="Random (recommended)", value="csr"),
                ListItem(label="Photo entropy", value="camera"),
                ListItem(label="Dice rolls", value="dice"),
            ],
            title="New wallet entropy",
        )

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        if event.button == Button.B and event.kind == EventKind.LONG:
            self.done = True
            self.result = None
            return
        self._list.on_event(event)
        if self._list.confirmed is not None:
            self.done = True
            self.result = str(self._list.confirmed)

    def draw(self, fb: FrameBuffer) -> None:
        self._list.draw(fb)

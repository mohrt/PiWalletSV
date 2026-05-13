"""restore-wallet orchestrator tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from piwallet.bonnet import restore_wallet as rw
from piwallet.bonnet.choosers import WordCountChooser
from piwallet.core import mnemonic as mnem
from piwallet.core.vault import Vault
from piwallet.ui.display import HeadlessDisplay
from piwallet.ui.input import FakeInputBackend, InputManager
from piwallet.ui.word_entry import MnemonicEntryScreen


@pytest.fixture()
def vault(tmp_path: Path) -> Vault:
    v = Vault(tmp_path / "vault.bin")
    v.create(pin="123456")
    return v


@pytest.fixture()
def display() -> HeadlessDisplay:
    return HeadlessDisplay()


@pytest.fixture()
def input_mgr() -> InputManager:
    return InputManager(FakeInputBackend())


def _stub_run_screen(
    handlers: dict[type, Callable[[object], None]],
) -> Callable[..., object]:
    def fake_run_screen(display, input_mgr, screen, **_kwargs):
        for screen_cls, handler in handlers.items():
            if isinstance(screen, screen_cls):
                handler(screen)
                break
        else:
            raise AssertionError(f"no handler for screen type {type(screen)!r}")
        return screen.result

    return fake_run_screen


def test_restore_happy_path_saves_wallet(
    monkeypatch: pytest.MonkeyPatch,
    vault: Vault,
    display: HeadlessDisplay,
    input_mgr: InputManager,
) -> None:
    real_phrase = mnem.generate(12)

    def chooser_done(s):
        s.done = True
        s.result = 12

    def entry_done(s):
        s.done = True
        s.result = real_phrase

    monkeypatch.setattr(
        rw,
        "run_screen",
        _stub_run_screen(
            {WordCountChooser: chooser_done, MnemonicEntryScreen: entry_done},
        ),
    )
    outcome = rw.run_restore_wallet(display, input_mgr, vault, pin="123456")
    assert outcome.error is None
    assert outcome.wallet is not None
    assert outcome.wallet.label == "restored-1"
    saved = vault.list_wallets()
    assert len(saved) == 1
    assert saved[0].id == outcome.wallet.id


def test_restore_24_word_phrase(
    monkeypatch: pytest.MonkeyPatch,
    vault: Vault,
    display: HeadlessDisplay,
    input_mgr: InputManager,
) -> None:
    phrase24 = mnem.generate(24)

    def chooser_done(s):
        s.done = True
        s.result = 24

    def entry_done(s):
        s.done = True
        s.result = phrase24

    monkeypatch.setattr(
        rw,
        "run_screen",
        _stub_run_screen(
            {WordCountChooser: chooser_done, MnemonicEntryScreen: entry_done},
        ),
    )
    outcome = rw.run_restore_wallet(display, input_mgr, vault, pin="123456")
    assert outcome.wallet is not None
    assert outcome.wallet.word_count == 24


def test_restore_cancel_at_chooser(
    monkeypatch: pytest.MonkeyPatch,
    vault: Vault,
    display: HeadlessDisplay,
    input_mgr: InputManager,
) -> None:
    def chooser_cancel(s):
        s.done = True
        s.result = None

    monkeypatch.setattr(
        rw,
        "run_screen",
        _stub_run_screen({WordCountChooser: chooser_cancel}),
    )
    outcome = rw.run_restore_wallet(display, input_mgr, vault, pin="123456")
    assert outcome.cancelled is True
    assert outcome.wallet is None
    assert vault.list_wallets() == []


def test_restore_propagates_checksum_failure(
    monkeypatch: pytest.MonkeyPatch,
    vault: Vault,
    display: HeadlessDisplay,
    input_mgr: InputManager,
) -> None:
    def chooser_done(s):
        s.done = True
        s.result = 12

    def entry_error(s):
        s.done = True
        s.result = None
        s.error = "BIP39 checksum failed: words don't add up"

    monkeypatch.setattr(
        rw,
        "run_screen",
        _stub_run_screen(
            {WordCountChooser: chooser_done, MnemonicEntryScreen: entry_error},
        ),
    )
    outcome = rw.run_restore_wallet(display, input_mgr, vault, pin="123456")
    assert outcome.wallet is None
    assert outcome.error is not None and "checksum" in outcome.error.lower()
    assert vault.list_wallets() == []


def test_restore_default_label_avoids_collisions(
    monkeypatch: pytest.MonkeyPatch,
    vault: Vault,
    display: HeadlessDisplay,
    input_mgr: InputManager,
) -> None:
    vault.add_wallet("123456", mnem.generate(12), label="restored-1")

    real_phrase = mnem.generate(12)

    def chooser_done(s):
        s.done = True
        s.result = 12

    def entry_done(s):
        s.done = True
        s.result = real_phrase

    monkeypatch.setattr(
        rw,
        "run_screen",
        _stub_run_screen(
            {WordCountChooser: chooser_done, MnemonicEntryScreen: entry_done},
        ),
    )
    outcome = rw.run_restore_wallet(display, input_mgr, vault, pin="123456")
    assert outcome.wallet is not None
    assert outcome.wallet.label == "restored-2"


def test_word_count_chooser_long_b_cancels() -> None:
    from piwallet.ui.input import Button, Event, EventKind

    chooser = WordCountChooser()
    chooser.on_event(Event(button=Button.B, kind=EventKind.LONG, at_ms=0))
    assert chooser.done is True
    assert chooser.result is None


def test_word_count_chooser_picks_12() -> None:
    from piwallet.ui.input import Button, Event, EventKind

    chooser = WordCountChooser()
    chooser.on_event(Event(button=Button.A, kind=EventKind.PRESS, at_ms=0))
    assert chooser.done is True
    assert chooser.result == 12


def test_word_count_chooser_picks_24() -> None:
    from piwallet.ui.input import Button, Event, EventKind

    chooser = WordCountChooser()
    chooser.on_event(Event(button=Button.DOWN, kind=EventKind.PRESS, at_ms=0))
    chooser.on_event(Event(button=Button.A, kind=EventKind.PRESS, at_ms=0))
    assert chooser.result == 24


def test_word_count_chooser_draws_smoke() -> None:
    from piwallet.ui.display import FrameBuffer
    fb = FrameBuffer()
    WordCountChooser().draw(fb)

"""create-wallet orchestrator tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from piwallet.bonnet import create_wallet as cw
from piwallet.bonnet.choosers import EntropySourceChooser, WordCountChooser
from piwallet.core.vault import Vault
from piwallet.ui.display import HeadlessDisplay
from piwallet.ui.input import FakeInputBackend, InputManager
from piwallet.ui.label_entry import WalletLabelEntryScreen
from piwallet.ui.show_phrase import ShowPhraseScreen
from piwallet.ui.word_pick_confirm import MnemonicConfirmPickScreen


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


def _wc_12(screen: WordCountChooser) -> None:
    screen.done = True
    screen.result = 12


def _entropy_csr(screen: EntropySourceChooser) -> None:
    screen.done = True
    screen.result = "csr"


def _label_use_default(screen: WalletLabelEntryScreen) -> None:
    screen.done = True
    screen.result = None


def _label_custom_river(screen: WalletLabelEntryScreen) -> None:
    screen.done = True
    screen.result = "river"


def _stub_run_screen(
    handlers: dict[type, Callable[[object], None]],
) -> Callable[..., object]:
    """Return a stub for ``run_screen`` that dispatches on screen type.

    For each screen passed in, the matching handler mutates the screen
    to a finished state (sets ``done`` and ``result``); the stub then
    returns ``screen.result``.
    """

    def fake_run_screen(display, input_mgr, screen, **_kwargs):
        for screen_cls, handler in handlers.items():
            if isinstance(screen, screen_cls):
                handler(screen)
                break
        else:
            raise AssertionError(f"no handler for screen type {type(screen)!r}")
        return screen.result

    return fake_run_screen


def test_create_happy_path_saves_wallet(
    monkeypatch: pytest.MonkeyPatch,
    vault: Vault,
    display: HeadlessDisplay,
    input_mgr: InputManager,
) -> None:
    def show_done(s):
        s.done = True
        s.result = True

    def pick_done(s: MnemonicConfirmPickScreen):
        s.done = True
        s.result = " ".join(s.phrase_words)

    monkeypatch.setattr(
        cw,
        "run_screen",
        _stub_run_screen(
            {
                WordCountChooser: _wc_12,
                EntropySourceChooser: _entropy_csr,
                ShowPhraseScreen: show_done,
                MnemonicConfirmPickScreen: pick_done,
                WalletLabelEntryScreen: _label_use_default,
            },
        ),
    )

    outcome = cw.run_create_wallet(display, input_mgr, vault, pin="123456")
    assert outcome.error is None
    assert outcome.cancelled is False
    assert outcome.wallet is not None
    assert outcome.wallet.label == "wallet-1"
    assert vault.list_wallets()[0].id == outcome.wallet.id


def test_create_cancel_at_show_phrase(
    monkeypatch: pytest.MonkeyPatch,
    vault: Vault,
    display: HeadlessDisplay,
    input_mgr: InputManager,
) -> None:
    def show_cancel(s):
        s.done = True
        s.result = False

    monkeypatch.setattr(
        cw,
        "run_screen",
        _stub_run_screen(
            {
                WordCountChooser: _wc_12,
                EntropySourceChooser: _entropy_csr,
                ShowPhraseScreen: show_cancel,
            },
        ),
    )
    outcome = cw.run_create_wallet(display, input_mgr, vault, pin="123456")
    assert outcome.cancelled is True
    assert outcome.wallet is None
    assert outcome.error is None
    assert vault.list_wallets() == []


def test_create_cancel_at_confirm_picker(
    monkeypatch: pytest.MonkeyPatch,
    vault: Vault,
    display: HeadlessDisplay,
    input_mgr: InputManager,
) -> None:
    def show_done(s):
        s.done = True
        s.result = True

    def pick_cancel(s: MnemonicConfirmPickScreen):
        s.done = True
        s.result = None

    monkeypatch.setattr(
        cw,
        "run_screen",
        _stub_run_screen(
            {
                WordCountChooser: _wc_12,
                EntropySourceChooser: _entropy_csr,
                ShowPhraseScreen: show_done,
                MnemonicConfirmPickScreen: pick_cancel,
            },
        ),
    )
    outcome = cw.run_create_wallet(display, input_mgr, vault, pin="123456")
    assert outcome.wallet is None
    assert outcome.cancelled is True
    assert vault.list_wallets() == []


def test_create_saves_custom_label(
    monkeypatch: pytest.MonkeyPatch,
    vault: Vault,
    display: HeadlessDisplay,
    input_mgr: InputManager,
) -> None:
    def show_done(s):
        s.done = True
        s.result = True

    def pick_done(s: MnemonicConfirmPickScreen):
        s.done = True
        s.result = " ".join(s.phrase_words)

    monkeypatch.setattr(
        cw,
        "run_screen",
        _stub_run_screen(
            {
                WordCountChooser: _wc_12,
                EntropySourceChooser: _entropy_csr,
                ShowPhraseScreen: show_done,
                MnemonicConfirmPickScreen: pick_done,
                WalletLabelEntryScreen: _label_custom_river,
            },
        ),
    )
    outcome = cw.run_create_wallet(display, input_mgr, vault, pin="123456")
    assert outcome.wallet is not None
    assert outcome.wallet.label == "river"


def test_create_default_label_avoids_collisions(
    monkeypatch: pytest.MonkeyPatch,
    vault: Vault,
    display: HeadlessDisplay,
    input_mgr: InputManager,
) -> None:
    from piwallet.core import mnemonic as mnem

    vault.add_wallet("123456", mnem.generate(12), label="wallet-1")
    vault.add_wallet("123456", mnem.generate(12), label="wallet-2")

    def show_done(s):
        s.done = True
        s.result = True

    def pick_done(s: MnemonicConfirmPickScreen):
        s.done = True
        s.result = " ".join(s.phrase_words)

    monkeypatch.setattr(
        cw,
        "run_screen",
        _stub_run_screen(
            {
                WordCountChooser: _wc_12,
                EntropySourceChooser: _entropy_csr,
                ShowPhraseScreen: show_done,
                MnemonicConfirmPickScreen: pick_done,
                WalletLabelEntryScreen: _label_use_default,
            },
        ),
    )
    outcome = cw.run_create_wallet(display, input_mgr, vault, pin="123456")
    assert outcome.wallet is not None
    assert outcome.wallet.label == "wallet-3"


def test_create_rejects_bad_word_count(
    vault: Vault,
    display: HeadlessDisplay,
    input_mgr: InputManager,
) -> None:
    with pytest.raises(ValueError):
        cw.run_create_wallet(
            display,
            input_mgr,
            vault,
            pin="123456",
            word_count=15,
        )

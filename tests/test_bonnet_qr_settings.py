"""QR brightness persistence hooks."""

from __future__ import annotations

from pathlib import Path

from piwallet.bonnet.qr_settings import make_qr_background_hooks, qr_brightness_screen_kwargs
from piwallet.core.settings import BonnetSettings, load_settings


def test_hooks_persist_to_disk(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    settings = BonnetSettings()
    _bg, persist = make_qr_background_hooks(settings, settings_path=p)
    persist(124)
    assert load_settings(p).qr_background == 124


def test_screen_kwargs_shape() -> None:
    kw = qr_brightness_screen_kwargs(BonnetSettings(qr_background=93))
    assert kw["qr_background"] == 93
    assert callable(kw["on_qr_background_changed"])

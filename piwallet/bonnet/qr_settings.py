"""Wire QR screens to persisted :class:`BonnetSettings`."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from piwallet.core.settings import BonnetSettings, save_settings


def make_qr_background_hooks(
    settings: BonnetSettings | None,
    *,
    settings_path: Path | None = None,
    on_settings_changed: Callable[[BonnetSettings], None] | None = None,
) -> tuple[int, Callable[[int], None] | None]:
    """Return ``(initial_level, persist_callback)`` for QR screens."""
    state = {"settings": settings or BonnetSettings()}
    initial = state["settings"].qr_background

    def persist(level: int) -> None:
        updated = state["settings"].with_qr_background(level)
        save_settings(updated, settings_path)
        state["settings"] = updated
        if on_settings_changed is not None:
            on_settings_changed(updated)

    return initial, persist


def qr_brightness_screen_kwargs(
    settings: BonnetSettings | None,
    *,
    settings_path: Path | None = None,
    on_settings_changed: Callable[[BonnetSettings], None] | None = None,
) -> dict[str, int | Callable[[int], None]]:
    """Keyword args for :class:`~piwallet.ui.pairing_multipart_qr_screen.PairingMultipartQrScreen` and wallet detail."""
    qr_bg, on_change = make_qr_background_hooks(
        settings,
        settings_path=settings_path,
        on_settings_changed=on_settings_changed,
    )
    return {"qr_background": qr_bg, "on_qr_background_changed": on_change}


__all__ = [
    "make_qr_background_hooks",
    "qr_brightness_screen_kwargs",
]

"""Persistent global bonnet settings.

Lives at ``~/.piwallet-dev/settings.json`` (or a caller-supplied path).
Carries non-sensitive operator preferences — currently just display
brightness, with room for sleep timeout, panel rotation, frame rate
limit, etc. as the UX matures.

The file is **not** the encrypted vault. It's a plain JSON document,
readable with ``cat`` for debugging and safe to commit to backups
(no secrets, no per-device fingerprints). It deliberately mirrors
:mod:`piwallet.firstboot.terms` so the load/save/migration shape is
familiar:

- A single :class:`BonnetSettings` dataclass describes the schema.
- :data:`SETTINGS_SCHEMA_VERSION` tags the on-disk format; a strictly
  lower version on disk triggers a forward migration on load
  (additive only — we never silently drop fields).
- ``load_settings`` returns defaults if the file is missing or
  corrupt; ``save_settings`` writes pretty-printed JSON.

Keep this module **import-safe on macOS** (no Pi-only deps); the
settings page wires it up through dependency injection so headless
tests round-trip without touching real hardware.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from piwallet.ui.display import (
    MAX_BRIGHTNESS,
    MIN_BRIGHTNESS,
    clamp_brightness,
)

#: Version of the on-disk settings schema. Bump when adding required
#: fields; load_settings will migrate older files forward by filling
#: defaults.
SETTINGS_SCHEMA_VERSION: int = 1


@dataclass(frozen=True, slots=True)
class BonnetSettings:
    """User-tunable bonnet preferences."""

    schema_version: int = SETTINGS_SCHEMA_VERSION
    #: Software-dimming multiplier in ``[MIN_BRIGHTNESS, 1.0]``.
    brightness: float = MAX_BRIGHTNESS

    def with_brightness(self, level: float) -> BonnetSettings:
        """Return a copy with ``brightness`` clamped into the legal range."""
        return replace(self, brightness=clamp_brightness(level))


def default_settings_path() -> Path:
    """Return ``~/.piwallet-dev/settings.json`` (the default location)."""
    return Path.home() / ".piwallet-dev" / "settings.json"


def load_settings(path: Path | None = None) -> BonnetSettings:
    """Read :class:`BonnetSettings` from ``path``, or defaults if missing/corrupt.

    Forward-migrates older schema versions by filling defaults for
    any missing fields — never silently drops unknown keys, but
    likewise never panics on them: an admin who hand-edits the file
    can adopt new versions without losing their tweaks.
    """
    p = path if path is not None else default_settings_path()
    if not p.exists():
        return BonnetSettings()
    try:
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return BonnetSettings()
    if not isinstance(data, dict):
        return BonnetSettings()
    return BonnetSettings(
        schema_version=int(data.get("schema_version", SETTINGS_SCHEMA_VERSION)),
        brightness=clamp_brightness(
            float(data.get("brightness", MAX_BRIGHTNESS)),
        ),
    )


def save_settings(settings: BonnetSettings, path: Path | None = None) -> None:
    """Persist ``settings`` as pretty-printed JSON, creating parent dirs."""
    p = path if path is not None else default_settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(settings)
    # Always re-stamp the schema version on save so a field added in
    # this build's BonnetSettings is reflected on disk even if the file
    # was loaded under an older version.
    payload["schema_version"] = SETTINGS_SCHEMA_VERSION
    p.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Re-exports so callers don't need to import display constants separately.
# ---------------------------------------------------------------------------

__all__ = [
    "MAX_BRIGHTNESS",
    "MIN_BRIGHTNESS",
    "SETTINGS_SCHEMA_VERSION",
    "BonnetSettings",
    "default_settings_path",
    "load_settings",
    "save_settings",
]

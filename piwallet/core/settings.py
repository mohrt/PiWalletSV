"""Persistent global bonnet settings.

Lives at ``~/.piwallet/settings.json`` (or a caller-supplied path).
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
SETTINGS_SCHEMA_VERSION: int = 3

#: Sleep-timer presets surfaced in the Settings screen. Order is the
#: cycle order under L/R input: 1 min -> 5 min -> off -> 1 min -> ...
#: ``0`` means "never blank the panel"; any other value is a positive
#: idle duration in milliseconds before the backlight goes off.
SLEEP_TIMER_OPTIONS_MS: tuple[int, ...] = (60_000, 300_000, 0)

#: Brightness presets surfaced in the Settings cycle row (L/R).
#: Order is the cycle order: dimmest -> brightest -> wrap.
BRIGHTNESS_OPTIONS: tuple[float, ...] = (0.2, 0.4, 0.6, 0.8, 1.0)

#: Camera-type presets for the Settings cycle row.
#: ``"ov5647"``  — Arducam OV5647 Mini, fixed-focus. Requires
#:                 ``camera_auto_detect=0`` + ``dtoverlay=ov5647`` in
#:                 ``/boot/firmware/config.txt``. Autofocus calls skipped.
#: ``"imx708"``  — Raspberry Pi Camera Module 3 (IMX708), autofocus.
#:                 Requires ``camera_auto_detect=1`` (default) or
#:                 ``dtoverlay=imx708`` in config.txt.
#: ``"auto"``    — Let libcamera auto-detect. Use for other cameras or
#:                 when unsure. Autofocus attempted (silently ignored if
#:                 not supported).
CAMERA_TYPE_OPTIONS: tuple[str, ...] = ("ov5647", "imx708", "auto")

#: Default camera type. OV5647 Mini is the recommended hardware.
DEFAULT_CAMERA_TYPE: str = "ov5647"

#: Default screen sleep timer. Five minutes is long enough that the
#: bonnet doesn't blank during a multi-step recovery flow but short
#: enough that a forgotten unlocked device dims well before sleeping
#: hours of CPU on a wasted backlight.
DEFAULT_SLEEP_TIMEOUT_MS: int = 300_000


def _normalize_camera_type(raw: str) -> str:
    """Snap ``raw`` to a known preset, defaulting to ``"ov5647"`` on garbage."""
    if raw in CAMERA_TYPE_OPTIONS:
        return raw
    return DEFAULT_CAMERA_TYPE


def _normalize_sleep_timeout_ms(raw: int) -> int:
    """Snap ``raw`` to a known preset, defaulting to 5 min on garbage.

    The on-disk file is hand-editable, and we don't want a typo to
    bury the operator in an "infinite sleep" or a 1 ms panel-blank
    storm. We accept exact preset matches verbatim and fall back to
    the 5 min default for anything else (including negatives).
    """
    if raw in SLEEP_TIMER_OPTIONS_MS:
        return raw
    return DEFAULT_SLEEP_TIMEOUT_MS


@dataclass(frozen=True, slots=True)
class BonnetSettings:
    """User-tunable bonnet preferences."""

    schema_version: int = SETTINGS_SCHEMA_VERSION
    #: Software-dimming multiplier in ``[MIN_BRIGHTNESS, 1.0]``.
    brightness: float = MAX_BRIGHTNESS
    #: Idle duration before the backlight blanks. ``0`` disables sleep
    #: entirely (the panel stays lit until the bonnet exits).
    sleep_timeout_ms: int = DEFAULT_SLEEP_TIMEOUT_MS
    #: Which camera module is installed. Controls whether autofocus
    #: is attempted (OV5647 is fixed-focus; attempting AF only logs
    #: a harmless error, but skipping it is cleaner). See
    #: ``CAMERA_TYPE_OPTIONS`` for the valid values.
    camera_type: str = DEFAULT_CAMERA_TYPE

    def with_brightness(self, level: float) -> BonnetSettings:
        """Return a copy with ``brightness`` clamped into the legal range."""
        return replace(self, brightness=clamp_brightness(level))

    def with_sleep_timeout_ms(self, ms: int) -> BonnetSettings:
        """Return a copy with ``sleep_timeout_ms`` snapped to a preset."""
        return replace(self, sleep_timeout_ms=_normalize_sleep_timeout_ms(ms))


def default_settings_path() -> Path:
    """Return ``~/.piwallet/settings.json`` (the default location).

    Re-exported here as part of the historical settings-module API;
    the actual path lives in :mod:`piwallet.core.paths`.
    """
    from piwallet.core.paths import default_settings_path as _path

    return _path()


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
    # Forward-migrate fields added since the file was last written.
    # ``sleep_timeout_ms`` was introduced with schema v2; v1 files
    # silently default to the 5 min preset so the operator's first
    # interaction with the new feature isn't an indefinitely-on panel.
    return BonnetSettings(
        schema_version=int(data.get("schema_version", SETTINGS_SCHEMA_VERSION)),
        brightness=clamp_brightness(
            float(data.get("brightness", MAX_BRIGHTNESS)),
        ),
        sleep_timeout_ms=_normalize_sleep_timeout_ms(
            int(data.get("sleep_timeout_ms", DEFAULT_SLEEP_TIMEOUT_MS)),
        ),
        camera_type=_normalize_camera_type(
            str(data.get("camera_type", DEFAULT_CAMERA_TYPE)),
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
    "BRIGHTNESS_OPTIONS",
    "CAMERA_TYPE_OPTIONS",
    "DEFAULT_CAMERA_TYPE",
    "DEFAULT_SLEEP_TIMEOUT_MS",
    "MAX_BRIGHTNESS",
    "MIN_BRIGHTNESS",
    "SETTINGS_SCHEMA_VERSION",
    "SLEEP_TIMER_OPTIONS_MS",
    "BonnetSettings",
    "default_settings_path",
    "load_settings",
    "save_settings",
]

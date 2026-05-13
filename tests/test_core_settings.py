"""Persistent bonnet settings: load / save / migrate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from piwallet.core.settings import (
    DEFAULT_SLEEP_TIMEOUT_MS,
    SETTINGS_SCHEMA_VERSION,
    SLEEP_TIMER_OPTIONS_MS,
    BonnetSettings,
    load_settings,
    save_settings,
)
from piwallet.ui.display import MAX_BRIGHTNESS, MIN_BRIGHTNESS


def test_load_returns_defaults_when_file_missing(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "nope.json")
    assert settings == BonnetSettings()
    assert settings.brightness == MAX_BRIGHTNESS
    assert settings.schema_version == SETTINGS_SCHEMA_VERSION


def test_save_then_load_roundtrips(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    save_settings(BonnetSettings().with_brightness(0.55), p)
    reloaded = load_settings(p)
    assert reloaded.brightness == pytest.approx(0.55)
    assert reloaded.schema_version == SETTINGS_SCHEMA_VERSION


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    p = tmp_path / "nested" / "more" / "settings.json"
    save_settings(BonnetSettings(), p)
    assert p.exists()


def test_load_clamps_out_of_range_values(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"schema_version": 1, "brightness": 5.0}))
    s = load_settings(p)
    assert s.brightness == MAX_BRIGHTNESS

    p.write_text(json.dumps({"schema_version": 1, "brightness": -2.0}))
    s = load_settings(p)
    assert s.brightness == MIN_BRIGHTNESS


def test_load_returns_defaults_on_corrupt_json(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    p.write_text("{not valid json")
    s = load_settings(p)
    assert s == BonnetSettings()


def test_load_returns_defaults_when_top_level_not_a_dict(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    p.write_text("[]")
    s = load_settings(p)
    assert s == BonnetSettings()


def test_load_forward_migrates_missing_fields(tmp_path: Path) -> None:
    """An older file with only schema_version still loads with defaults filled in."""
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"schema_version": 1}))
    s = load_settings(p)
    assert s.brightness == MAX_BRIGHTNESS


def test_save_re_stamps_schema_version(tmp_path: Path) -> None:
    """Even if the in-memory dataclass kept an older version, save bumps it."""
    p = tmp_path / "settings.json"
    older = BonnetSettings(schema_version=0, brightness=0.7)
    save_settings(older, p)
    payload = json.loads(p.read_text())
    assert payload["schema_version"] == SETTINGS_SCHEMA_VERSION
    # And brightness is preserved across the stamp.
    assert payload["brightness"] == pytest.approx(0.7)


def test_with_brightness_clamps_into_legal_range() -> None:
    s = BonnetSettings()
    assert s.with_brightness(2.0).brightness == MAX_BRIGHTNESS
    assert s.with_brightness(0.0).brightness == MIN_BRIGHTNESS
    assert s.with_brightness(0.5).brightness == pytest.approx(0.5)


def test_with_brightness_returns_a_new_instance() -> None:
    s = BonnetSettings()
    s2 = s.with_brightness(0.4)
    assert s is not s2
    assert s.brightness == MAX_BRIGHTNESS  # unchanged


# ---------------------------------------------------------------------------
# Sleep timer (added in schema v2)
# ---------------------------------------------------------------------------


def test_default_sleep_timeout_is_5_minutes() -> None:
    """Default keeps the panel lit long enough for a recovery flow.

    A short default would cut off operators mid-mnemonic-entry; a
    long-but-not-infinite default avoids leaving an unattended
    unlocked device burning the backlight indefinitely.
    """
    assert DEFAULT_SLEEP_TIMEOUT_MS == 300_000
    assert BonnetSettings().sleep_timeout_ms == DEFAULT_SLEEP_TIMEOUT_MS


def test_sleep_timer_presets_are_1min_5min_off_in_cycle_order() -> None:
    """Cycle order matters — L/R steps through this tuple verbatim."""
    assert SLEEP_TIMER_OPTIONS_MS == (60_000, 300_000, 0)


def test_save_then_load_roundtrips_sleep_timer(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    save_settings(BonnetSettings().with_sleep_timeout_ms(60_000), p)
    reloaded = load_settings(p)
    assert reloaded.sleep_timeout_ms == 60_000


def test_load_v1_file_migrates_to_default_sleep_timeout(tmp_path: Path) -> None:
    """A v1 file lacks ``sleep_timeout_ms``; load fills the 5 min default."""
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"schema_version": 1, "brightness": 0.6}))
    s = load_settings(p)
    assert s.sleep_timeout_ms == DEFAULT_SLEEP_TIMEOUT_MS
    assert s.brightness == pytest.approx(0.6)


def test_load_v1_file_save_re_stamps_v2(tmp_path: Path) -> None:
    """Round-tripping a v1 file through save bumps the on-disk version to v2."""
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"schema_version": 1, "brightness": 0.6}))
    save_settings(load_settings(p), p)
    payload = json.loads(p.read_text())
    assert payload["schema_version"] == SETTINGS_SCHEMA_VERSION  # i.e. 2
    assert payload["sleep_timeout_ms"] == DEFAULT_SLEEP_TIMEOUT_MS


def test_load_snaps_unknown_sleep_timeout_to_default(tmp_path: Path) -> None:
    """Hand-edited file with a 17 s timeout falls back to the 5 min default."""
    p = tmp_path / "settings.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "brightness": 0.8,
                "sleep_timeout_ms": 17_000,  # not a preset
            }
        )
    )
    s = load_settings(p)
    assert s.sleep_timeout_ms == DEFAULT_SLEEP_TIMEOUT_MS


def test_load_accepts_off_preset(tmp_path: Path) -> None:
    """``0`` is the legal "Off" preset; load must keep it intact."""
    p = tmp_path / "settings.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "brightness": 0.7,
                "sleep_timeout_ms": 0,
            }
        )
    )
    assert load_settings(p).sleep_timeout_ms == 0


def test_with_sleep_timeout_ms_snaps_to_preset_and_returns_new_instance() -> None:
    s = BonnetSettings()
    # Exact preset stays intact.
    assert s.with_sleep_timeout_ms(60_000).sleep_timeout_ms == 60_000
    assert s.with_sleep_timeout_ms(0).sleep_timeout_ms == 0
    # Non-preset snaps back to the default.
    assert s.with_sleep_timeout_ms(17_000).sleep_timeout_ms == DEFAULT_SLEEP_TIMEOUT_MS
    # Original is untouched.
    assert s.sleep_timeout_ms == DEFAULT_SLEEP_TIMEOUT_MS

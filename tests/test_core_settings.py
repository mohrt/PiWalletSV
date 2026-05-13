"""Persistent bonnet settings: load / save / migrate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from piwallet.core.settings import (
    SETTINGS_SCHEMA_VERSION,
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

"""Coverage for :mod:`piwallet.core.paths` — the canonical filesystem
locations and the one-shot dev-dir migration.

The migration helper is the load-bearing piece here: it runs
unconditionally at every bonnet boot, and a misbehaving rename would
either silently lose a developer's vault or block first-boot setup
on a freshly-flashed image. Tests cover every branch of its logic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from piwallet.core.paths import (
    APP_DIR_NAME,
    LEGACY_APP_DIR_NAME,
    app_dir,
    default_settings_path,
    default_terms_path,
    default_vault_path,
    migrate_legacy_dev_dir,
)


@pytest.fixture(autouse=True)
def _clear_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Don't let the developer's own ``$PIWALLET_HOME`` bleed in."""
    monkeypatch.delenv("PIWALLET_HOME", raising=False)


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``Path.home()`` at a clean tmp_path and return it."""
    monkeypatch.setenv("HOME", str(tmp_path))
    # On macOS, ``Path.home()`` consults `pwd` rather than $HOME unless
    # we also patch the underlying `Path.expanduser`. Going through
    # the env var alone is sufficient on Linux (CI) and the tests we
    # care about here don't depend on the macOS path.
    return tmp_path


def test_app_dir_defaults_to_dot_piwallet(fake_home: Path) -> None:
    assert app_dir() == fake_home / APP_DIR_NAME


def test_app_dir_honors_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    override = tmp_path / "alt"
    monkeypatch.setenv("PIWALLET_HOME", str(override))
    assert app_dir() == override


def test_app_dir_does_not_create_directory(fake_home: Path) -> None:
    """Importing / calling must not side-effect the filesystem."""
    _ = app_dir()
    assert not (fake_home / APP_DIR_NAME).exists()


def test_default_paths_compose_under_app_dir(fake_home: Path) -> None:
    base = fake_home / APP_DIR_NAME
    assert default_vault_path() == base / "vault.bin"
    assert default_settings_path() == base / "settings.json"
    assert default_terms_path() == base / "terms.json"


# ---- migrate_legacy_dev_dir -----------------------------------------


def test_migrate_renames_legacy_when_canonical_missing(tmp_path: Path) -> None:
    legacy = tmp_path / LEGACY_APP_DIR_NAME
    legacy.mkdir()
    (legacy / "vault.bin").write_bytes(b"the seed lives here")

    moved = migrate_legacy_dev_dir(home=tmp_path)

    assert moved is True
    canonical = tmp_path / APP_DIR_NAME
    assert canonical.exists()
    assert (canonical / "vault.bin").read_bytes() == b"the seed lives here"
    assert not legacy.exists()


def test_migrate_is_noop_when_canonical_already_exists(tmp_path: Path) -> None:
    legacy = tmp_path / LEGACY_APP_DIR_NAME
    canonical = tmp_path / APP_DIR_NAME
    legacy.mkdir()
    canonical.mkdir()
    (legacy / "stale.bin").write_bytes(b"old")
    (canonical / "fresh.bin").write_bytes(b"new")

    moved = migrate_legacy_dev_dir(home=tmp_path)

    assert moved is False
    # Both directories untouched — we don't merge, we don't clobber.
    assert (legacy / "stale.bin").read_bytes() == b"old"
    assert (canonical / "fresh.bin").read_bytes() == b"new"


def test_migrate_is_noop_when_legacy_missing(tmp_path: Path) -> None:
    moved = migrate_legacy_dev_dir(home=tmp_path)
    assert moved is False
    assert not (tmp_path / APP_DIR_NAME).exists()


def test_migrate_is_noop_when_override_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit ``PIWALLET_HOME`` opts out of the rename entirely.

    A test or sandbox driving the app via the override flag does not
    want the helper second-guessing it by mutating files outside its
    sandbox.
    """
    monkeypatch.setenv("PIWALLET_HOME", str(tmp_path / "elsewhere"))
    legacy = tmp_path / LEGACY_APP_DIR_NAME
    legacy.mkdir()

    moved = migrate_legacy_dev_dir(home=tmp_path)

    assert moved is False
    assert legacy.exists()


def test_migrate_idempotent_across_repeated_calls(tmp_path: Path) -> None:
    legacy = tmp_path / LEGACY_APP_DIR_NAME
    legacy.mkdir()
    (legacy / "settings.json").write_text("{}", encoding="utf-8")

    first = migrate_legacy_dev_dir(home=tmp_path)
    second = migrate_legacy_dev_dir(home=tmp_path)
    third = migrate_legacy_dev_dir(home=tmp_path)

    assert (first, second, third) == (True, False, False)
    assert (tmp_path / APP_DIR_NAME / "settings.json").read_text(encoding="utf-8") == "{}"


def test_migrate_handles_rename_oserror_without_raising(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed rename (cross-device, perms, etc.) must surface but
    not crash the bonnet — we still want the operator to be able to
    boot into the disclaimer/unlock flow with an explicit
    --vault-path override pointing at the legacy directory.
    """
    legacy = tmp_path / LEGACY_APP_DIR_NAME
    legacy.mkdir()

    def _boom(self: Path, target: Path) -> Path:
        raise OSError("simulated EXDEV")

    monkeypatch.setattr(Path, "rename", _boom)
    caplog.set_level("WARNING", logger="piwallet.core.paths")

    moved = migrate_legacy_dev_dir(home=tmp_path)

    assert moved is False
    assert legacy.exists()
    assert any(
        "could not migrate legacy" in rec.getMessage() for rec in caplog.records
    )


def test_migrate_logs_success_for_journald(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    legacy = tmp_path / LEGACY_APP_DIR_NAME
    legacy.mkdir()
    caplog.set_level("WARNING", logger="piwallet.core.paths")

    migrate_legacy_dev_dir(home=tmp_path)

    assert any(
        "migrated legacy state directory" in rec.getMessage() for rec in caplog.records
    )

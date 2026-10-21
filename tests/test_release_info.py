"""Sealed-image release file reader tests."""

from __future__ import annotations

from pathlib import Path

from piwallet.platform.release import read_image_id


def test_read_image_id_from_release_file(tmp_path: Path) -> None:
    release = tmp_path / "piwalletsv-release"
    release.write_text(
        "# Written by deploy/provision-pi.sh — do not hand-edit.\n"
        "PIWALLETSV_VERSION=0.1.0-r1\n"
        "PIWALLETSV_IMAGE_ID=480c6679\n"
        'PIWALLETSV_BOARD_MODEL="Raspberry Pi 3 Model B Rev 1.2"\n',
        encoding="utf-8",
    )
    assert read_image_id(release) == "480c6679"


def test_read_image_id_missing_file_or_key(tmp_path: Path) -> None:
    assert read_image_id(tmp_path / "missing") is None
    release = tmp_path / "piwalletsv-release"
    release.write_text("PIWALLETSV_VERSION=0.1.0-r1\nPIWALLETSV_IMAGE_ID=\n", encoding="utf-8")
    assert read_image_id(release) is None

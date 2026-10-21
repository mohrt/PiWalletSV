"""Read the sealed-image release metadata written by ``deploy/provision-pi.sh``."""

from __future__ import annotations

from pathlib import Path

_RELEASE_FILE = Path("/etc/piwalletsv-release")


def read_image_id(path: Path = _RELEASE_FILE) -> str | None:
    """Return ``PIWALLETSV_IMAGE_ID`` (e.g. ``480c6679``), or ``None`` off-image."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "PIWALLETSV_IMAGE_ID":
            return value.strip().strip('"') or None
    return None

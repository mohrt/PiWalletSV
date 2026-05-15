"""Canonical filesystem paths for PiWalletSV's per-user state.

Single source of truth for ``~/.piwallet/`` and the three files
that live in it:

  * ``vault.bin``    — encrypted seeds + per-wallet metadata.
  * ``settings.json`` — bonnet UI settings (brightness, sleep timeout).
  * ``terms.json``   — disclaimer-acceptance state (one-shot per
    disclaimer version).

The directory used to be ``~/.piwallet-dev/`` from when the project
was developer-only. The "-dev" suffix has no meaning on a sealed
SD-card image where the user never sees a shell, so the canonical
location is now plain ``~/.piwallet/``. :func:`migrate_legacy_dev_dir`
provides a one-shot rename for existing developer setups; called once
at bonnet boot, idempotent thereafter.

Override
--------
The ``PIWALLET_HOME`` environment variable, if set, redirects the
state directory wholesale (e.g. ``PIWALLET_HOME=/tmp/piw-test`` for
unit tests). The migration helper is a no-op when the override is
in effect — we don't second-guess an explicit operator choice.

Production deployments (the systemd unit on the SD-card image) leave
``PIWALLET_HOME`` unset and write to ``~/.piwallet/`` under the
``pwsv`` user's home.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

LOG = logging.getLogger(__name__)

#: Canonical state-directory name (under ``$HOME``).
APP_DIR_NAME = ".piwallet"

#: Legacy state-directory name kept around purely for the one-shot
#: migration. Never write to it; never read from it after a
#: :func:`migrate_legacy_dev_dir` call has had a chance to run.
LEGACY_APP_DIR_NAME = ".piwallet-dev"


def app_dir() -> Path:
    """Return the directory PiWalletSV stores its per-user state in.

    Honors ``$PIWALLET_HOME`` when set, otherwise ``~/.piwallet/``.
    Does **not** create the directory — leave that to the consumer
    that's about to write something into it, so a stray import
    doesn't side-effect the filesystem.
    """
    override = os.environ.get("PIWALLET_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / APP_DIR_NAME


def default_vault_path() -> Path:
    """``<app_dir>/vault.bin``."""
    return app_dir() / "vault.bin"


def default_settings_path() -> Path:
    """``<app_dir>/settings.json``."""
    return app_dir() / "settings.json"


def default_terms_path() -> Path:
    """``<app_dir>/terms.json``."""
    return app_dir() / "terms.json"


def migrate_legacy_dev_dir(home: Path | None = None) -> bool:
    """One-shot rename of ``~/.piwallet-dev/`` to ``~/.piwallet/``.

    Idempotent. Does nothing — and returns ``False`` — if any of the
    following hold:

      * ``$PIWALLET_HOME`` is set (explicit override; we don't
        second-guess the operator).
      * The canonical directory already exists (already migrated, or
        a fresh install on an image).
      * The legacy directory doesn't exist (fresh install, image
        deployment, or already migrated and cleaned up).

    Returns ``True`` on a real rename. Logs a warning either way so
    journald captures the event for the operator.

    Failures (cross-device move, permission denied, etc.) log a
    warning and return ``False`` — the caller can still operate
    against an explicit ``--vault-path`` override if it must, but
    that's a developer-tools fallback, not a production path.
    """
    if os.environ.get("PIWALLET_HOME"):
        return False

    base = home if home is not None else Path.home()
    canonical = base / APP_DIR_NAME
    legacy = base / LEGACY_APP_DIR_NAME

    if canonical.exists() or not legacy.exists():
        return False

    try:
        legacy.rename(canonical)
    except OSError as exc:
        LOG.warning(
            "could not migrate legacy %s -> %s: %s",
            legacy,
            canonical,
            exc,
        )
        return False

    LOG.warning(
        "migrated legacy state directory %s -> %s",
        legacy,
        canonical,
    )
    return True


__all__ = [
    "APP_DIR_NAME",
    "LEGACY_APP_DIR_NAME",
    "app_dir",
    "default_settings_path",
    "default_terms_path",
    "default_vault_path",
    "migrate_legacy_dev_dir",
]

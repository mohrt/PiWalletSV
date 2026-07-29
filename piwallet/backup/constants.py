"""On-stick layout constants for PiWalletSV signer backups."""

from __future__ import annotations

#: Top-level folder on the USB volume (sibling to user DCIM etc.).
STICK_ROOT_DIRNAME = "PiWalletSV"

#: Timestamped export directories live here.
BACKUPS_SUBDIR = "backups"

#: Filenames inside each export directory.
MANIFEST_FILENAME = "manifest.json"
VAULT_FILENAME = "vault.bin"
STATE_FILENAME = "state.bin"
SETTINGS_FILENAME = "settings.json"
TERMS_FILENAME = "terms.json"

#: Manifest ``format`` field value.
MANIFEST_FORMAT = "piwallet-signer-backup"

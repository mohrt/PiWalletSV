#!/usr/bin/env bash
# Legacy path — delegates to the copy shipped inside the Python package.
exec "$(dirname "$0")/../../piwallet/backup/usb_mount.sh" "$@"

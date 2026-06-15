#!/usr/bin/env bash
# Copy only Pi runtime firmware paths (allowlist). Safer than exclude-only rsync:
# new top-level dirs on the workstation (e.g. images/) never reach the Pi.
#
# Usage:
#   bash scripts/rsync-pi-payload.sh /path/to/PiWallet user@pi:~/PiWallet/
#   bash scripts/rsync-pi-payload.sh /path/to/PiWallet /tmp/payload/
#
set -euo pipefail

SRC=${1:?usage: rsync-pi-payload.sh SRC DEST/}
DEST=${2:?usage: rsync-pi-payload.sh SRC DEST/}

SRC=$(cd "$SRC" && pwd)
INCLUDES="$SRC/scripts/rsync-pi-includes.txt"
EXCLUDES="$SRC/scripts/rsync-pi-excludes.txt"
[[ -f "$INCLUDES" ]] || {
    echo "rsync-pi-payload: missing $INCLUDES" >&2
    exit 1
}
[[ -f "$EXCLUDES" ]] || {
    echo "rsync-pi-payload: missing $EXCLUDES" >&2
    exit 1
}

# rsync remote paths need a trailing slash on DEST for directory merges.
case "$DEST" in
    */) ;;
    *) DEST="${DEST}/" ;;
esac

while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" ]] && continue

    local_src="$SRC/$line"
    [[ -e "$local_src" ]] || {
        echo "rsync-pi-payload: missing include path: $line" >&2
        exit 1
    }

    if [[ "$line" == */ ]]; then
        rsync -a --delete --exclude-from="$EXCLUDES" "${local_src}" "${DEST}${line}"
    else
        rsync -a --exclude-from="$EXCLUDES" "${local_src}" "${DEST}"
    fi
    echo "rsync-pi-payload: synced $line"
done < "$INCLUDES"

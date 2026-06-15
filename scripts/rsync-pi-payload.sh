#!/usr/bin/env bash
# Copy only Pi runtime firmware paths (allowlist). Safer than exclude-only rsync:
# new top-level dirs on the workstation (e.g. images/) never reach the Pi.
#
# Usage:
#   bash scripts/rsync-pi-payload.sh /path/to/PiWallet user@pi:~/PiWallet/
#   bash scripts/rsync-pi-payload.sh /path/to/PiWallet /tmp/payload/
#
# Environment (set by sync-to-pi.sh for one SSH login):
#   SYNC_PI_SSH_SOCKET   OpenSSH ControlPath for shared connection
#   RSYNC_RSH            rsync -e value, e.g. "ssh -S /tmp/sync-to-pi.abc"
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

ssh_cmd() {
    if [[ -n "${SYNC_PI_SSH_SOCKET:-}" ]]; then
        ssh -S "$SYNC_PI_SSH_SOCKET" "$@"
    else
        ssh "$@"
    fi
}

# rsync remote paths need a trailing slash on DEST for directory merges.
case "$DEST" in
    */) ;;
    *) DEST="${DEST}/" ;;
esac

ensure_dest_exists() {
    case "$DEST" in
        *:*)  # user@host:path — rsync won't create missing parent dirs
            local remote="${DEST%%:*}"
            local remote_path="${DEST#*:}"
            remote_path="${remote_path%/}"
            ssh_cmd "$remote" "mkdir -p -- ${remote_path}"
            ;;
        *)
            mkdir -p "$DEST"
            ;;
    esac
}

ensure_dest_exists

# One rsync (one SSH session) instead of per-path rsync invocations.
FILTER=()
while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" ]] && continue

    [[ -e "$SRC/$line" ]] || {
        echo "rsync-pi-payload: missing include path: $line" >&2
        exit 1
    }

    if [[ "$line" == */ ]]; then
        FILTER+=(--include "${line}" --include "${line}***")
    else
        FILTER+=(--include "$line")
    fi
done < "$INCLUDES"
FILTER+=(--exclude-from="$EXCLUDES" --exclude '*')

RSYNC_ARGS=(-a --delete "${FILTER[@]}" "${SRC}/" "${DEST}")
if [[ -n "${RSYNC_RSH:-}" ]]; then
    rsync -e "$RSYNC_RSH" "${RSYNC_ARGS[@]}"
else
    rsync "${RSYNC_ARGS[@]}"
fi
echo "rsync-pi-payload: synced allowlist from $(basename "$SRC")/"

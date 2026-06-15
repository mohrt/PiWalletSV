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

remote_clean_junk() {
    local remote=$1
    local remote_path=$2
    ssh_cmd "$remote" "bash -s" -- "$remote_path" <<'EOF'
set -euo pipefail
ROOT=${1:?}
for sub in piwallet scripts deploy; do
    [[ -d "$ROOT/$sub" ]] || continue
    find "$ROOT/$sub" \( -type d -name __pycache__ -o -name '*.pyc' -o -name '*.pyo' \) -print0 2>/dev/null |
        while IFS= read -r -d '' p; do
            rm -rf "$p" 2>/dev/null || sudo -n rm -rf "$p" 2>/dev/null || true
        done
done
EOF
}

case "$DEST" in
    *:*)
        remote="${DEST%%:*}"
        remote_path="${DEST#*:}"
        remote_path="${remote_path%/}"
        echo "rsync-pi-payload: clean remote junk under ${remote_path}"
        remote_clean_junk "$remote" "$remote_path"
        ;;
esac

# One rsync (one SSH session). Filter order matters: broad "***" includes must
# come AFTER exclude-from, or __pycache__/*.pyc from the Mac get re-sent every sync.
FILTER=()
FILE_INCLUDES=()
while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" ]] && continue
    [[ -e "$SRC/$line" ]] || {
        echo "rsync-pi-payload: missing include path: $line" >&2
        exit 1
    }
    if [[ "$line" == */ ]]; then
        FILTER+=(--include "${line}")
    else
        FILE_INCLUDES+=("$line")
    fi
done < "$INCLUDES"

FILTER+=(--exclude-from="$EXCLUDES")
while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" ]] && continue
    [[ -e "$SRC/$line" ]] || continue
    if [[ "$line" == */ ]]; then
        FILTER+=(--include "${line}***")
    fi
done < "$INCLUDES"
for f in "${FILE_INCLUDES[@]:-}"; do
    FILTER+=(--include "$f")
done
FILTER+=(--exclude '*')

# --delete keeps remote in sync with transferred files; do not use --delete-excluded —
# root-owned __pycache__ on the Pi (from sudo provision) cannot be unlinked by pisv.
RSYNC_ARGS=(-a --delete "${FILTER[@]}" "${SRC}/" "${DEST}")
if [[ -n "${RSYNC_RSH:-}" ]]; then
    rsync -e "$RSYNC_RSH" "${RSYNC_ARGS[@]}"
else
    rsync "${RSYNC_ARGS[@]}"
fi
echo "rsync-pi-payload: synced allowlist from $(basename "$SRC")/"

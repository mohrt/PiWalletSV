#!/usr/bin/env bash
# Remove paths that must not ship on a Pi (dev sync or production image).
# Reads patterns from scripts/rsync-pi-excludes.txt.
#
# Usage:
#   bash scripts/prune-pi-payload.sh [ROOT]
#   bash scripts/prune-pi-payload.sh /opt/piwallet
set -euo pipefail

ROOT="${1:-.}"
ROOT="$(cd "$ROOT" && pwd)"
EXCLUDE_FILE="$ROOT/scripts/rsync-pi-excludes.txt"

if [[ ! -f "$EXCLUDE_FILE" ]]; then
    echo "prune-pi-payload: missing $EXCLUDE_FILE" >&2
    exit 1
fi

prune_literal() {
    local rel=$1
    local target="$ROOT/$rel"
    if [[ -e "$target" ]]; then
        if rm -rf "$target" 2>/dev/null; then
            echo "prune-pi-payload: removed $rel"
        elif command -v sudo &>/dev/null && sudo -n rm -rf "$target" 2>/dev/null; then
            echo "prune-pi-payload: removed (sudo) $rel"
        else
            echo "prune-pi-payload: skip (permission denied) $rel" >&2
        fi
    fi
}

prune_glob() {
    local pattern=$1
    local count=0
    while IFS= read -r -d '' path; do
        if rm -rf "$path" 2>/dev/null; then
            count=$((count + 1))
        elif command -v sudo &>/dev/null && sudo -n rm -rf "$path" 2>/dev/null; then
            count=$((count + 1))
        fi
    done < <(find "$ROOT" -name "$pattern" -print0 2>/dev/null)
    if [[ $count -gt 0 ]]; then
        echo "prune-pi-payload: removed $count path(s) matching $pattern"
    fi
}

# Runtime dirs created on the Pi after sync (venv, local vault). Must stay
# excluded from rsync (Mac → Pi) but must NOT be deleted by prune on a live
# ~/PiWallet — otherwise every sync-to-pi wipes the bootstrap venv.
RUNTIME_KEEP=(.venv venv env .piwallet .piwallet-dev)

is_runtime_keep() {
    local rel=$1 item
    for item in "${RUNTIME_KEEP[@]}"; do
        [[ "$rel" == "$item" ]] && return 0
    done
    return 1
}

while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" ]] && continue

    case "$line" in
        *\**)
            prune_glob "$line"
            ;;
        *)
            if is_runtime_keep "$line"; then
                continue
            fi
            prune_literal "$line"
            ;;
    esac
done < "$EXCLUDE_FILE"

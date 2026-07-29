#!/usr/bin/env bash
# Remove paths that must not ship on a Pi (dev sync or production image).
# Reads patterns from scripts/rsync-pi-excludes.txt.
#
# Paths listed in KEEP_ON_PI are rsync-excluded (do not copy from the Mac)
# but are created on the Pi and must survive prune.
#
# Usage:
#   bash scripts/prune-pi-payload.sh [ROOT]
#   bash scripts/prune-pi-payload.sh /opt/piwallet
set -euo pipefail

ROOT="${1:-.}"
ROOT="$(cd "$ROOT" && pwd)"
EXCLUDE_FILE="$ROOT/scripts/rsync-pi-excludes.txt"

# Rsync-exclude only — leave these alone on the Pi.
KEEP_ON_PI=(
    .venv
    venv
    env
)

if [[ ! -f "$EXCLUDE_FILE" ]]; then
    echo "prune-pi-payload: missing $EXCLUDE_FILE" >&2
    exit 1
fi

should_keep() {
    local rel=$1
    local k
    for k in "${KEEP_ON_PI[@]}"; do
        if [[ "$rel" == "$k" ]]; then
            return 0
        fi
    done
    return 1
}

prune_literal() {
    local rel=$1
    if should_keep "$rel"; then
        return 0
    fi
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

while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" ]] && continue

    case "$line" in
        *\**)
            prune_glob "$line"
            ;;
        *)
            prune_literal "$line"
            ;;
    esac
done < "$EXCLUDE_FILE"

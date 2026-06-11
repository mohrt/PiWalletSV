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
        rm -rf "$target"
        echo "prune-pi-payload: removed $rel"
    fi
}

prune_glob() {
    local pattern=$1
    local found=0
    while IFS= read -r -d '' path; do
        rm -rf "$path"
        echo "prune-pi-payload: removed ${path#"$ROOT"/}"
        found=1
    done < <(find "$ROOT" -name "$pattern" -print0 2>/dev/null)
    return 0
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

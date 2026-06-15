#!/usr/bin/env bash
# Remove excluded runtime junk under a Pi payload tree (__pycache__, *.pyc, caches).
# After sudo provision, bytecode under ~/PiWallet may be root-owned; use sudo -n when
# passwordless sudo is available (typical builder Pis).
#
# Usage:
#   bash scripts/clean-pi-payload-junk.sh [ROOT]
set -euo pipefail

ROOT="${1:-.}"
ROOT="$(cd "$ROOT" && pwd)"

rm_path() {
    local p="$1"
    [[ -e "$p" ]] || return 0
    if rm -rf "$p" 2>/dev/null; then
        echo "clean-pi-payload-junk: removed ${p#"$ROOT"/}"
        return 0
    fi
    if [[ "$(id -u)" -eq 0 ]]; then
        return 0
    fi
    if command -v sudo &>/dev/null && sudo -n rm -rf "$p" 2>/dev/null; then
        echo "clean-pi-payload-junk: removed (sudo) ${p#"$ROOT"/}"
        return 0
    fi
    echo "clean-pi-payload-junk: skip (permission denied) ${p#"$ROOT"/}" >&2
    return 0
}

prune_name_under() {
    local base=$1
    local pattern=$2
    [[ -d "$base" ]] || return 0
    while IFS= read -r -d '' path; do
        rm_path "$path"
    done < <(find "$base" -name "$pattern" -print0 2>/dev/null)
}

for sub in piwallet scripts deploy; do
    prune_name_under "$ROOT/$sub" __pycache__
    prune_name_under "$ROOT/$sub" .pytest_cache
    prune_name_under "$ROOT/$sub" .ruff_cache
    prune_name_under "$ROOT/$sub" .mypy_cache
done

for pattern in '*.pyc' '*.pyo'; do
    while IFS= read -r -d '' path; do
        rm_path "$path"
    done < <(find "$ROOT/piwallet" "$ROOT/scripts" "$ROOT/deploy" -name "$pattern" -print0 2>/dev/null)
done

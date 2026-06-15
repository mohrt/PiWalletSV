#!/usr/bin/env bash
# Verify a directory is a valid Pi runtime payload (required files present,
# excluded dev/docs/secrets absent). Used after sync-to-pi and provision-pi.
#
# Usage:
#   bash scripts/verify-pi-payload.sh [ROOT]
set -euo pipefail

ROOT="${1:-.}"
ROOT="$(cd "$ROOT" && pwd)"
FAILURES=0

fail() {
    printf 'verify-pi-payload: %s\n' "$*" >&2
    FAILURES=$((FAILURES + 1))
}

REQUIRED=(
    pyproject.toml
    deploy/provision-pi.sh
    deploy/purge-radio-packages.sh
    deploy/systemd/piwallet-purge-radios.service
    deploy/systemd/piwallet-bonnet.service
    piwallet/__init__.py
    scripts/install-piwallet-deps.sh
    scripts/setup-bonnet-hardware.sh
    scripts/factory-smoke-test.sh
    scripts/rsync-pi-includes.txt
    scripts/rsync-pi-payload.sh
    scripts/rsync-pi-excludes.txt
    scripts/prune-pi-payload.sh
    scripts/verify-pi-payload.sh
)

for path in "${REQUIRED[@]}"; do
    if [[ ! -e "$ROOT/$path" ]]; then
        fail "missing required path: $path"
    fi
done

EXCLUDE_FILE="$ROOT/scripts/rsync-pi-excludes.txt"
if [[ ! -f "$EXCLUDE_FILE" ]]; then
    fail "missing exclude manifest: scripts/rsync-pi-excludes.txt"
    exit 1
fi

while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" ]] && continue

    if [[ "$line" == *"*"* ]]; then
        if find "$ROOT" -name "$line" -print -quit 2>/dev/null | grep -q .; then
            fail "forbidden glob present: $line"
        fi
        continue
    fi

    if [[ -e "$ROOT/$line" ]]; then
        fail "forbidden path present: $line"
    fi
done < "$EXCLUDE_FILE"

if [[ $FAILURES -eq 0 ]]; then
    echo "verify-pi-payload: OK ($ROOT)"
    exit 0
fi

printf 'verify-pi-payload: %d check(s) failed\n' "$FAILURES" >&2
exit 1

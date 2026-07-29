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
    scripts/clean-pi-payload-junk.sh
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

# Rsync-exclude only — these are created on the Pi and must remain.
KEEP_ON_PI=(
    .venv
    venv
    env
)

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

while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" ]] && continue

    if should_keep "$line"; then
        continue
    fi

    if [[ "$line" == *"*"* ]]; then
        # Scope glob checks to synced source dirs only — .venv/ and other runtime
        # directories legitimately contain *.pyc and should not trigger a failure.
        if find "$ROOT/piwallet" "$ROOT/scripts" "$ROOT/deploy" \
               -name "$line" -print -quit 2>/dev/null | grep -q .; then
            fail "forbidden glob present in source dirs: $line"
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

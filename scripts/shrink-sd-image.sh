#!/usr/bin/env bash
#
# Shrink a captured Raspberry Pi SD .img so it fits 8 GB microSD cards.
#
# Uses PiShrink (https://github.com/Drewsif/PiShrink). On macOS, runs inside
# Docker because loop mounts and resize2fs need Linux.
#
# Usage:
#   ./scripts/shrink-sd-image.sh piwalletsv-0.1.0-r3.img
#   ./scripts/shrink-sd-image.sh input.img -o output.img
#
# Environment:
#   PISHRINK   path to pishrink script (Linux native)
#   PISHRINK_DOCKER_IMAGE  Docker image for macOS (default: debian:bookworm-slim)
#   PISHRINK_AUTOEXPAND=1  enable PiShrink first-boot expand (adds one reboot on
#                          flash; default is off — shrunk image already fits 8 GB)
#
set -euo pipefail

readonly LOG_PREFIX="[shrink-sd]"
readonly PISHRINK_URL="https://raw.githubusercontent.com/Drewsif/PiShrink/master/pishrink.sh"

INPUT=""
OUTPUT=""
INPLACE=0

log()  { printf '%s %s\n' "$LOG_PREFIX" "$*"; }
fail() { printf '%s error: %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

usage() {
    sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-2}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -o|--output) OUTPUT=${2:?--output requires a path}; shift ;;
        -o=*|--output=*) OUTPUT=${1#*=} ;;
        -h|--help) usage 0 ;;
        -*) fail "unknown option '$1'" ;;
        *)
            if [[ -z "$INPUT" ]]; then
                INPUT=$1
            else
                fail "unexpected arg '$1'"
            fi
            ;;
    esac
    shift
done

[[ -n "$INPUT" ]] || fail "input .img path required"
[[ -f "$INPUT" ]] || fail "input not found: $INPUT"
[[ "$INPUT" == *.img ]] || fail "input must be a .img file: $INPUT"

if [[ -z "$OUTPUT" ]]; then
    OUTPUT="${INPUT%.img}.shrunk.img"
    INPLACE=1
fi

INPUT=$(cd "$(dirname "$INPUT")" && pwd)/$(basename "$INPUT")
OUTPUT=$(cd "$(dirname "$OUTPUT")" && pwd)/$(basename "$OUTPUT")

PISHRINK_FLAGS=()
if [[ "${PISHRINK_AUTOEXPAND:-0}" != 1 ]]; then
    PISHRINK_FLAGS=(-s)
    log "PiShrink: skip first-boot auto-expand (no flash-time reboot; set PISHRINK_AUTOEXPAND=1 to fill larger cards)"
fi

run_pishrink_native() {
    local pishrink_bin="${PISHRINK:-}"
    if [[ -z "$pishrink_bin" ]]; then
        if command -v pishrink >/dev/null 2>&1; then
            pishrink_bin=$(command -v pishrink)
        elif [[ -x ./pishrink ]]; then
            pishrink_bin=./pishrink
        fi
    fi
    [[ -n "$pishrink_bin" && -x "$pishrink_bin" ]] || return 1
    log "PiShrink (native): $pishrink_bin"
    sudo "$pishrink_bin" "${PISHRINK_FLAGS[@]}" "$INPUT" "$OUTPUT"
}

run_pishrink_docker() {
    command -v docker >/dev/null 2>&1 || fail "docker not found — install Docker Desktop for macOS shrink"
    local img="${PISHRINK_DOCKER_IMAGE:-debian:bookworm-slim}"
    local workdir
    workdir=$(dirname "$INPUT")
    log "PiShrink (docker:$img)"
    docker run --rm --privileged \
        -v "$workdir:/workdir" \
        -w /workdir \
        "$img" \
        bash -ec "
            set -euo pipefail
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq
            apt-get install -y -qq e2fsprogs parted kpartx mount util-linux ca-certificates wget >/dev/null
            wget -q -O /usr/local/bin/pishrink '$PISHRINK_URL'
            chmod +x /usr/local/bin/pishrink
            pishrink ${PISHRINK_FLAGS[*]:-} '/workdir/$(basename "$INPUT")' '/workdir/$(basename "$OUTPUT")'
        "
}

before=$(stat -f%z "$INPUT" 2>/dev/null || stat -c%s "$INPUT")
log "input=$(basename "$INPUT") size=$((before / 1024 / 1024)) MiB"

if [[ "$(uname -s)" == Linux ]] && run_pishrink_native; then
    :
elif [[ "$(uname -s)" == Darwin ]]; then
    run_pishrink_docker
elif run_pishrink_native; then
    :
else
    fail "PiShrink not available — set PISHRINK or install Docker (macOS)"
fi

[[ -f "$OUTPUT" ]] || fail "output missing: $OUTPUT"

after=$(stat -f%z "$OUTPUT" 2>/dev/null || stat -c%s "$OUTPUT")
log "output=$(basename "$OUTPUT") size=$((after / 1024 / 1024)) MiB"

if [[ $INPLACE -eq 1 ]]; then
    mv -f "$OUTPUT" "$INPUT"
    log "replaced $INPUT"
else
    log "wrote $OUTPUT"
fi

final=$(stat -f%z "$INPUT" 2>/dev/null || stat -c%s "$INPUT")
max=$((8 * 1024 * 1024 * 1024))
if [[ $final -gt $max ]]; then
    printf '%s WARN: shrunk image still > 8 GiB — verify before publishing\n' "$LOG_PREFIX" >&2
else
    log "OK — fits 8 GB cards (uncompressed ≤ 8 GiB)"
fi

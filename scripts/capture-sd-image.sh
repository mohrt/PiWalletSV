#!/usr/bin/env bash
#
# Capture a sealed PiWalletSV SD card → shrink → xz → SHA256SUMS.
#
# Usage:
#   ./scripts/capture-sd-image.sh --version 0.1.0-r3 /dev/rdisk4
#   ./scripts/capture-sd-image.sh --version 0.1.0-r3 disk4 --yes
#   ./scripts/capture-sd-image.sh --version 0.1.0-r3 --from images/raw-capture.img
#   ./scripts/capture-sd-image.sh --version 0.1.0-r3 --board pi0 --maturity beta disk4
#   ./scripts/capture-sd-image.sh --version 0.1.0-r3 --board pi0 --maturity alpha disk4
#
# Options:
#   --version VER      release version (required)
#   --board SLUG       processor tier (required) — SeedSigner-style:
#                      pi0 (Zero v1.3 / Zero W / WH), pi02w (Zero 2 W, Pi 3 B),
#                      pi2 (Pi 2 B), pi4 (Pi 4 / 400)
#   --maturity STAGE   alpha | beta | release (default: release)
#                      alpha/beta add a suffix to the filename; alpha stays local
#   --from PATH        skip dd — shrink/compress/checksum an existing .img capture
#   --output-dir D     directory for artifacts (default: images/, or images/alpha/)
#   --keep-img         keep uncompressed .img after xz (xz -k)
#   --sign             gpg --armor --detach-sign the .img.xz and SHA256SUMS
#   --yes              skip interactive device confirmation
#
# Filenames:
#   release → piwalletsv-0.1.0-r3-pi0.img.xz           (GitHub GA)
#   beta    → piwalletsv-0.1.0-r3-pi0-beta.img.xz      (GitHub pre-release)
#   alpha   → piwalletsv-0.1.0-r3-pi0-alpha.img.xz     (local only — never upload)
#
# Requires: sudo (dd), xz, shasum/sha256sum; Docker on macOS for shrink.
#
set -euo pipefail

readonly LOG_PREFIX="[capture-sd]"
readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly SHRINK="$ROOT/scripts/shrink-sd-image.sh"

VERSION=""
BOARD=""
MATURITY="release"
DEVICE=""
FROM_IMG=""
OUT_DIR=""
KEEP_IMG=0
DO_SIGN=0
ASSUME_YES=0

log()  { printf '%s %s\n' "$LOG_PREFIX" "$*"; }
fail() { printf '%s error: %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

usage() {
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-2}"
}

filesize_mib() {
    local path=$1
    local bytes
    bytes=$(stat -f%z "$path" 2>/dev/null || stat -c%s "$path")
    echo $((bytes / 1024 / 1024))
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --version)     VERSION=${2:?--version requires a value}; shift ;;
        --version=*)   VERSION=${1#*=} ;;
        --board)       BOARD=${2:?--board requires a value}; shift ;;
        --board=*)     BOARD=${1#*=} ;;
        --maturity)    MATURITY=${2:?--maturity requires a value}; shift ;;
        --maturity=*)  MATURITY=${1#*=} ;;
        --from)        FROM_IMG=${2:?--from requires a path}; shift ;;
        --from=*)      FROM_IMG=${1#*=} ;;
        --output-dir)  OUT_DIR=${2:?--output-dir requires a path}; shift ;;
        --output-dir=*) OUT_DIR=${1#*=} ;;
        --keep-img)    KEEP_IMG=1 ;;
        --sign)        DO_SIGN=1 ;;
        --yes|-y)      ASSUME_YES=1 ;;
        -h|--help)     usage 0 ;;
        -*)            fail "unknown option '$1'" ;;
        *)
            if [[ -z "$DEVICE" ]]; then
                DEVICE=$1
            else
                fail "unexpected arg '$1'"
            fi
            ;;
    esac
    shift
done

[[ -n "$VERSION" ]] || fail "--version is required"
[[ -n "$BOARD" ]] || fail "--board is required (e.g. pi0 for Zero / Zero W)"
[[ "$VERSION" != *"/"* ]] || fail "invalid version: $VERSION"

case "$BOARD" in
    pi0|pi02w|pi2|pi4) ;;
    *) fail "--board must be pi0, pi02w, pi2, or pi4 (got '$BOARD')" ;;
esac

case "$MATURITY" in
    alpha|beta|release) ;;
    *) fail "--maturity must be alpha, beta, or release (got '$MATURITY')" ;;
esac

if [[ -n "$FROM_IMG" && -n "$DEVICE" ]]; then
    fail "pass either a device or --from, not both"
fi
if [[ -z "$FROM_IMG" && -z "$DEVICE" ]]; then
    fail "device path required (or use --from to skip capture)"
fi

if [[ -z "$OUT_DIR" ]]; then
    if [[ "$MATURITY" == alpha ]]; then
        OUT_DIR="$ROOT/images/alpha"
    else
        OUT_DIR="$ROOT/images"
    fi
fi

mkdir -p "$OUT_DIR"
OUT_DIR=$(cd "$OUT_DIR" && pwd)

image_basename() {
    local base="piwalletsv-${VERSION}-${BOARD}"
    case "$MATURITY" in
        alpha|beta) printf '%s-%s' "$base" "$MATURITY" ;;
        release)    printf '%s' "$base" ;;
    esac
}

readonly IMAGE_SLUG="$(image_basename)"
IMG="$OUT_DIR/${IMAGE_SLUG}.img"
XZ="$OUT_DIR/${IMAGE_SLUG}.img.xz"
SUMS="$OUT_DIR/SHA256SUMS"

[[ -x "$SHRINK" ]] || fail "missing shrink helper: $SHRINK"

disk_path() {
    local dev=$1
    [[ "$dev" == /* ]] || dev="/dev/$dev"
    if [[ "$(uname -s)" == Darwin ]]; then
        dev="${dev/rdisk/disk}"
    fi
    echo "$dev"
}

dd_path() {
    local dev=$1
    [[ "$dev" == /* ]] || dev="/dev/$dev"
    if [[ "$(uname -s)" == Darwin ]]; then
        dev="${dev/disk/rdisk}"
    fi
    echo "$dev"
}

show_device() {
    local dev=$1
    if [[ "$(uname -s)" == Darwin ]]; then
        diskutil list "$(disk_path "$dev")" || true
    elif command -v lsblk >/dev/null 2>&1; then
        lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,MODEL "$(disk_path "$dev")" || true
    else
        log "device: $(disk_path "$dev")"
    fi
}

confirm_device() {
    local dev=$1
    local dd_dev
    dd_dev=$(dd_path "$dev")
    local token="${dd_dev##*/}"

    printf '\n' >&2
    printf '%s WARNING: about to read the entire contents of %s\n' "$LOG_PREFIX" "$dd_dev" >&2
    printf '%s          into %s\n' "$LOG_PREFIX" "$IMG" >&2
    printf '%s          Triple-check this is the Pi SD card, not your system disk.\n' "$LOG_PREFIX" >&2
    show_device "$dev" >&2
    printf '\n' >&2
    if [[ $ASSUME_YES -eq 1 ]]; then
        log "continuing (--yes)"
        return
    fi
    printf '%s Type %s to confirm: ' "$LOG_PREFIX" "$token" >&2
    local reply
    read -r reply
    [[ "$reply" == "$token" ]] || fail "confirmation failed — aborted"
}

unmount_device() {
    local dev=$1
    if [[ "$(uname -s)" == Darwin ]]; then
        diskutil unmountDisk "$(disk_path "$dev")"
    else
        local disk
        disk=$(disk_path "$dev")
        if findmnt -rn "$disk" >/dev/null 2>&1; then
            sudo umount "${disk}"* 2>/dev/null || sudo umount "$disk" || true
        fi
    fi
}

capture_dd() {
    local dev=$1
    local dd_dev
    dd_dev=$(dd_path "$dev")

    [[ -f "$IMG" ]] && fail "$IMG already exists — remove it, use --from, or pick --output-dir"

    confirm_device "$dev"
    unmount_device "$dev"

    log "capturing $dd_dev → $(basename "$IMG")"
    if [[ "$(uname -s)" == Darwin ]]; then
        sudo dd if="$dd_dev" of="$IMG" bs=4m conv=sync,noerror status=progress
    else
        sudo dd if="$dd_dev" of="$IMG" bs=4M status=progress conv=fsync
    fi
    sync
    log "capture done — $(filesize_mib "$IMG") MiB"
}

stage_from_img() {
    local src=$1
    [[ -f "$src" ]] || fail "input not found: $src"
    [[ "$src" == *.img ]] || fail "input must be a .img file: $src"
    src=$(cd "$(dirname "$src")" && pwd)/$(basename "$src")

    if [[ "$src" == "$IMG" ]]; then
        log "using existing $(basename "$IMG")"
        return
    fi

    log "staging $(basename "$src") → $(basename "$IMG")"
    if [[ -f "$IMG" ]]; then
        fail "$IMG already exists — move it aside or use --output-dir"
    fi
    mv "$src" "$IMG"
}

run_shrink() {
    log "shrinking $(basename "$IMG")"
    bash "$SHRINK" "$IMG"
    log "shrink done — $(filesize_mib "$IMG") MiB"
}

run_xz() {
    local xz_args=(-f -T0)
    [[ $KEEP_IMG -eq 1 ]] && xz_args=(-f -T0 -k)

    log "compressing $(basename "$IMG") → $(basename "$XZ")"
    xz "${xz_args[@]}" "$IMG"

    [[ -f "$XZ" ]] || fail "missing compressed image: $XZ"
    log "compressed — $(filesize_mib "$XZ") MiB"

    if command -v xz >/dev/null 2>&1; then
        log "xz -l (uncompressed size must be ≤ ~8 GiB for 8 GB cards):"
        xz -l "$XZ" || true
    fi
}

write_sha256sums() {
    local hash name line
    name=$(basename "$XZ")

    if command -v shasum >/dev/null 2>&1; then
        hash=$(shasum -a 256 "$XZ" | awk '{print $1}')
    else
        hash=$(sha256sum "$XZ" | awk '{print $1}')
    fi
    line="$hash  $name"

    # Single-line file for GitHub Release upload (this version only).
    log "writing upload bundle $(basename "$SUMS")"
    printf '%s\n' "$line" > "$SUMS"

    # Cumulative manifest in repo — one line per published image (not alpha).
    if [[ "$MATURITY" == alpha ]]; then
        log "skipping releases/SHA256SUMS (alpha builds stay local)"
        return
    fi

    local release_sums="$ROOT/releases/SHA256SUMS"
    log "updating releases/SHA256SUMS"
    if [[ -f "$release_sums" ]]; then
        grep -v "  ${name}$" "$release_sums" > "${release_sums}.tmp" || true
    else
        : > "${release_sums}.tmp"
    fi
    printf '%s\n' "$line" >> "${release_sums}.tmp"
    sort -k2 "${release_sums}.tmp" -o "$release_sums"
    rm -f "${release_sums}.tmp"

    update_releases_json "$hash"
}

update_releases_json() {
    local hash=$1
    [[ "$MATURITY" == alpha ]] && return 0
    local manifest="$ROOT/releases/releases.json"
    [[ -f "$manifest" ]] || return 0

    python3 - "$manifest" "$VERSION" "$BOARD" "$MATURITY" "$hash" <<'PY'
import json
import sys

path, version, board, maturity, sha256 = sys.argv[1:6]
with open(path, encoding="utf-8") as f:
    data = json.load(f)

base = f"piwalletsv-{version}-{board}"
if maturity in ("alpha", "beta"):
    base = f"{base}-{maturity}"
image_xz = f"{base}.img.xz"

for rel in data.get("releases", []):
    if rel.get("version") != version:
        continue
    if rel.get("board") not in (None, board):
        continue
    rel["board"] = board
    rel["sha256"] = sha256
    tag = rel.get("tag", f"v{version}")
    base_url = f"https://github.com/mohrt/PiWalletSV/releases/download/{tag}"
    assets = rel.setdefault("assets", {})
    assets["image_xz"] = f"{base_url}/{image_xz}"
    assets["image_asc"] = f"{base_url}/{image_xz}.asc"
    assets["sha256sums"] = f"{base_url}/SHA256SUMS"
    assets["sha256sums_asc"] = f"{base_url}/SHA256SUMS.asc"
    break
else:
    print(
        f"[capture-sd] warn: version {version} (board {board}) not found in releases.json",
        file=sys.stderr,
    )
    sys.exit(0)

with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
    log "updated releases.json for $VERSION ($BOARD)"
}

run_sign() {
    command -v gpg >/dev/null 2>&1 || fail "gpg not found (--sign)"
    log "signing $(basename "$XZ")"
    gpg --armor --detach-sign "$XZ"
    log "signing $(basename "$SUMS")"
    gpg --armor --detach-sign "$SUMS"
}

# --- main ---

if [[ -n "$FROM_IMG" ]]; then
    stage_from_img "$FROM_IMG"
else
    capture_dd "$DEVICE"
fi

run_shrink
run_xz
write_sha256sums

if [[ $DO_SIGN -eq 1 ]]; then
    run_sign
fi

log "done ($BOARD $MATURITY)"
log "artifact: $XZ"
log "checksum: $SUMS"
[[ $DO_SIGN -eq 1 ]] && log "signatures: ${XZ}.asc ${SUMS}.asc"

#!/usr/bin/env bash
#
# Build PiWalletSV docs and/or companion for prod or dev mirrors.
#
# Dev:
#   docs site      → dev.piwalletsv.com      (Launch wallet → app.dev.piwalletsv.com)
#   companion app  → app.dev.piwalletsv.com  (footer docs → dev.piwalletsv.com)
#
# Prod:
#   docs site      → piwalletsv.com
#   companion app  → app.piwalletsv.com
#
# Usage:
#   ./publish.sh docs [--env dev|prod]
#   ./publish.sh companion [--env dev|prod]
#   ./publish.sh all [--env dev|prod]
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

ENV=prod
TARGET=all

usage() {
  cat <<'EOF'
Usage: ./publish.sh [docs|companion|all] [--env dev|prod]

  docs       mkdocs build → ./site/
  companion  vite build  → ./companion/dist/
  all        both (default)

  --env dev   dev.piwalletsv.com / app.dev.piwalletsv.com
  --env prod  piwalletsv.com / app.piwalletsv.com (default)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      ENV="${2:?--env requires dev or prod}"
      shift 2
      ;;
    docs|companion|all)
      TARGET="$1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

case "$ENV" in
  dev|prod) ;;
  *)
    echo "bad --env '$ENV' (expected dev or prod)" >&2
    exit 1
    ;;
esac

if [[ "$ENV" == "dev" ]]; then
  export PIWALLETSV_COMPANION_URL=https://app.dev.piwalletsv.com
  export MKDOCS_SITE_URL=https://dev.piwalletsv.com/
  export PIWALLETSV_STORE_API_URL=https://store.dev.piwalletsv.com
  export PIWALLETSV_STORE_DEV_BANNER="Test store — no real orders shipped."
  COMPANION_DOCS=https://dev.piwalletsv.com
else
  export PIWALLETSV_COMPANION_URL=https://app.piwalletsv.com
  export MKDOCS_SITE_URL=https://piwalletsv.com/
  export PIWALLETSV_STORE_API_URL=https://store.piwalletsv.com
  unset PIWALLETSV_STORE_DEV_BANNER
  COMPANION_DOCS=https://piwalletsv.com
fi

build_docs() {
  python3 -m pip install -q -r requirements-docs.txt
  mkdocs build --strict
  echo "[publish] docs → site/  env=$ENV  companion_url=$PIWALLETSV_COMPANION_URL"
}

build_companion() {
  (cd companion && npm ci && VITE_DOCS_BASE_URL="$COMPANION_DOCS" npm run build)
  echo "[publish] companion → companion/dist/  env=$ENV  docs=$COMPANION_DOCS"
}

case "$TARGET" in
  docs) build_docs ;;
  companion) build_companion ;;
  all)
    build_docs
    build_companion
    ;;
esac

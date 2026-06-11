#!/usr/bin/env bash
# Deprecated: use scripts/sync-to-pi.sh (canonical excludes + verify).
#
#   ./scripts/sync-to-pi.sh pisv@piwalletsv32.local --bootstrap
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT/scripts/sync-to-pi.sh" pisv@piwalletsv32.local "$@"

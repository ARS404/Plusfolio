#!/bin/sh
# Shared-host entry point: check existing tools; never install or update the host.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3 is required. Ask the server administrator to provide it; no system packages were changed.' >&2
  exit 1
fi
exec python3 scripts/server.py init "$@"

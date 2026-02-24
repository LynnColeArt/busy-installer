#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install Python 3.10+ and rerun." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}/../../..${PYTHONPATH:+:${PYTHONPATH}}"
exec python3 -m busy_installer.platform.launcher "$@"

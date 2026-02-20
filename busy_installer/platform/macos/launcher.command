#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKDIR="${SCRIPT_DIR%/*}"
MANIFEST="${SCRIPT_DIR}/../../docs/installer-manifest.yaml"
LOG_FILE="${WORKDIR}/busy-installer.log"

python3 -m busy_installer.cli --manifest "${MANIFEST}" --workspace "${WORKDIR}" install "$@" | tee -a "${LOG_FILE}"

open "http://127.0.0.1:8080" >/dev/null 2>&1 || true

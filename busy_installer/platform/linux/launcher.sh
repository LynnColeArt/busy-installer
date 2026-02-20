#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
WORKDIR="${BUSY_INSTALL_DIR:-${HOME}/pillowfort}"
MANIFEST="${BUSY_INSTALL_MANIFEST:-${REPO_ROOT}/docs/installer-manifest.yaml}"
LOG_FILE="${WORKDIR}/busy-installer.log"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install Python 3.10+ and rerun." >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git not found. Install git and rerun." >&2
  exit 1
fi

if [[ ! -d "${REPO_ROOT}/busy_installer" ]]; then
  echo "Repository root is invalid: ${REPO_ROOT}" >&2
  exit 1
fi

mkdir -p "${WORKDIR}"
cd "${REPO_ROOT}"

if ! python3 -c "import busy_installer.cli" >/dev/null 2>&1; then
  echo "Could not import busy_installer from ${REPO_ROOT}. Run from a valid busy-installer checkout." >&2
  exit 1
fi

EXTRA_ARGS=()
if [[ "${BUSY_INSTALL_STRICT_SOURCE:-0}" == "1" ]]; then
  EXTRA_ARGS+=(--strict-source)
fi
if [[ "${BUSY_INSTALL_ALLOW_COPY_FALLBACK:-0}" == "1" ]]; then
  EXTRA_ARGS+=(--allow-copy-fallback)
fi

python3 -m busy_installer.cli --manifest "${MANIFEST}" --workspace "${WORKDIR}" install "${EXTRA_ARGS[@]}" "$@" | tee -a "${LOG_FILE}"


if [[ -n "${MANIFEST_UI_OPEN:-}" ]]; then
  xdg-open "http://127.0.0.1:8080" >/dev/null 2>&1 || true
fi

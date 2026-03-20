#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
VENV_PYTHON="${ROOT_DIR}/.venv/bin/python"
BOOTSTRAP="${ROOT_DIR}/scripts/bootstrap_env.py"

if [[ -x "${VENV_PYTHON}" ]]; then
  BOOTSTRAP_PYTHON="${VENV_PYTHON}"
elif command -v python3 >/dev/null 2>&1; then
  BOOTSTRAP_PYTHON="python3"
else
  echo "Python 3 not found and ${VENV_PYTHON} is missing. Install Python 3.10+ and rerun." >&2
  exit 1
fi

"${BOOTSTRAP_PYTHON}" "${BOOTSTRAP}" >/dev/null
if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "bootstrap completed but ${VENV_PYTHON} is missing." >&2
  exit 1
fi
export PYTHONPATH="${ROOT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
exec "${VENV_PYTHON}" -m busy_installer.app "$@"

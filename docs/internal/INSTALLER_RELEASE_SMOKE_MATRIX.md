# Installer Release Smoke Matrix

## Purpose

This document closes the remaining manual packaging/release-smoke gap tracked in
the Busy execution queue after the installer wrapper/runtime hardening pass.

It does **not** introduce CI/workflow automation. That remains deferred until
Lynn Cole is involved in CI/workflow decisions.

## Current Host Command

From the `busy-installer` repo root:

```bash
python3 scripts/bootstrap_env.py --dev
.venv/bin/python scripts/release_smoke.py --current-platform --skip-bootstrap
```

The repo-owned smoke command validates the current host by:

- running the full Python test suite
- running the bundled-manifest dry-run smoke harness
- syntax-checking the POSIX wrappers on POSIX hosts
- exercising the repo-root `pf` wrapper in a temp workspace with browser-open disabled

## Manual OS Matrix

### macOS

```bash
python3 scripts/bootstrap_env.py --dev
.venv/bin/python -m pytest -q
.venv/bin/python scripts/smoke_manifest.py
.venv/bin/python scripts/release_smoke.py --current-platform --skip-bootstrap
bash -n busy_installer/platform/macos/launcher.command
```

### Linux

```bash
python3 scripts/bootstrap_env.py --dev
.venv/bin/python -m pytest -q
.venv/bin/python scripts/smoke_manifest.py
.venv/bin/python scripts/release_smoke.py --current-platform --skip-bootstrap
bash -n busy_installer/platform/linux/launcher.sh
```

### Windows

```powershell
py -3 scripts\bootstrap_env.py --dev
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts\smoke_manifest.py
.venv\Scripts\python.exe scripts\release_smoke.py --current-platform --skip-bootstrap
.\pf.ps1 --workspace $env:TEMP\pillowfort-release-smoke --dry-run
```

## Acceptance

- Python tests pass in the repo-local `.venv`
- the bundled-manifest smoke harness passes
- the current-platform repo wrapper completes a dry-run install path cleanly
- platform-native launcher syntax/entrypoint checks pass on the relevant OS
- failures are visible as command exit failures, not only in logs

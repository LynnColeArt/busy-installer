# Installer Multi-Platform Wrapper Feature Spec

**Owner:** platform
**Priority:** P0 (installer drift pre-close)
**Scope:** `busy-installer`

## Purpose

Validate the same first-run onboarding-first behavior across Linux/macOS/Windows launchers while keeping management UX launch behavior deterministic and non-blocking.

## Wrapper Entrypoints

- Linux: `busy_installer/platform/linux/launcher.sh`
- macOS: `busy_installer/platform/macos/launcher.command`
- Windows: `busy_installer/platform/windows/launcher.ps1`

All entrypoints must route to `busy_installer.platform.launcher`.

## Required Behavior Matrix

| Case | Expected command | Management open policy |
| --- | --- | --- |
| `install` (default) | Launches installer command with manifest/workspace defaults and env overrides | Open management URL when `wrappers.open_management_on_complete` is true and `BUSY_INSTALL_MANAGEMENT_URL` exists |
| `repair` | Same passthrough behavior as `install` | Open management URL when wrapper/manifest policy allows |
| `status` | Invoke CLI status command | Never open management UI |
| `clean` / other passthrough | Invoke CLI command | Never open management UI |

## Determinism and Failure Semantics

- Wrapper must read policy defaults from manifest:
  - `wrappers.open_management_on_complete`
  - `wrappers.management_url`
- Env variables override manifest where present:
  - `MANIFEST_UI_OPEN`
  - `BUSY_INSTALL_MANAGEMENT_URL`
- Installer execution and logging must remain authoritative:
  - successful install/repair writes `install` log entry
  - failing install/repair returns non-zero and does not attempt management launch
- Management open is **best-effort only**:
  - failure to launch browser/UI must log a warning and still return success when install/repair succeeds

## Replay / Drift Checks (expected for revalidation)

- Confirm all three launchers contain `busy_installer.platform.launcher` as the entrypoint.
- Confirm manifest-driven wrapper policy is honored by all platform entrypoints.
- Verify install-first behavior:
  - default args invoke install path
  - onboarding workflow remains in installer manifest `workflows.onboarding`
- Confirm management open fallback on platforms without browser opener support.

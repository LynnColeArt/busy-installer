# Installer Multi-Platform Wrapper Feature Spec

**Owner:** platform
**Priority:** P0 (installer drift pre-close)
**Scope:** `busy-installer`

## Purpose

Validate the same frictionless first-run and repeat-run behavior across
Linux/macOS/Windows entrypoints while keeping completion-surface routing
deterministic and browser launch behavior non-blocking.

## Wrapper Entrypoints

- Linux: `busy_installer/platform/linux/launcher.sh`
- macOS: `busy_installer/platform/macos/launcher.command`
- Windows: `busy_installer/platform/windows/launcher.ps1`
- Repo-local bootstrap commands: `./pf`, `./pillowfort`, `./busy`, `pf.cmd`, `pillowfort.cmd`, `busy.cmd`, `./pf.ps1`, `./pillowfort.ps1`, `./busy.ps1`

User-facing entrypoints must route to `busy_installer.app`.
The app may delegate to `busy_installer.platform.launcher`, but launcher is an
implementation detail rather than the primary user contract.
Repo-local wrappers and platform launchers should bootstrap the repo-local
`.venv` automatically before launching the app.
Installed console scripts run inside their existing interpreter and are not
required to create a repo-local `.venv`.

## Security-Critical Modules

The following modules are security-critical for this feature area and should be
reviewed together when one of them changes:

- `busy_installer/core/config.py`
  - fail-closed manifest parsing for authority fields
- `busy_installer/core/runner.py`
  - repo sync, provider-catalog source selection, and source-of-truth
    enforcement
- `busy_installer/platform/launcher.py`
  - wrapper argument parsing, command routing, and management bootstrap
    ownership
- `busy_installer/platform/management_bootstrap.py`
  - local runtime ownership checks and browser-root readiness gating

## Required Behavior Matrix

| Case | Expected command | Completion-surface policy |
| --- | --- | --- |
| default user entrypoint (`pf`, `busy`, `pillowfort`, platform launcher with no explicit command) | Bootstrap runtime deps if needed, then run maintenance-first `repair` flow with manifest/workspace defaults and env overrides | If browser-open policy is enabled, open onboarding when `<workspace>/.busy/onboarding/state.json` is missing or not `ACTIVE`; otherwise bootstrap local management on `127.0.0.1:8031` and open management |
| explicit `install` | Launch explicit install workflow | Same state-driven completion-surface routing as default |
| explicit `repair` | Launch explicit repair workflow | Same state-driven completion-surface routing as default |
| `status` | Invoke CLI status command | Never open onboarding or management UI |
| `clean` / other passthrough | Invoke CLI command | Never open onboarding or management UI |

## Determinism and Failure Semantics

- Wrapper must read policy defaults from manifest:
  - `wrappers.open_management_on_complete`
  - `wrappers.onboarding_url`
  - `wrappers.management_url`
- User-facing entrypoints must be self-bootstrapping:
  - repo-local wrappers/platform launchers create/update the repo-local `.venv`
    when needed
  - installed console scripts run inside the environment where the package is
    already installed
  - repo-local wrappers/platform launchers install the pinned runtime
    dependency set before app launch, but must reuse an unchanged prepared
    `.venv` instead of rerunning packaging operations on every launch
- Env variables override manifest where present:
  - `MANIFEST_UI_OPEN`
  - `BUSY_INSTALL_ONBOARDING_URL`
  - `BUSY_INSTALL_MANAGEMENT_URL` when it still identifies the local machine
    (`localhost`, loopback, wildcard bind, or this machine's hostname/IP)
- Installer execution and logging must remain authoritative:
  - successful maintenance/install writes `install` log entry
  - failing install/repair returns non-zero and does not attempt browser launch
- Bundled repo sync must materialize the management runtime:
  - `busy38-management-ui` is synced into `busy-38-ongoing/vendor/busy-38-management-ui`
  - until the same-origin root-serving fix is on the default management-ui
    branch, the bundled manifest may pin the repo to the reviewed branch that
    contains that fix so fresh installs remain self-consistent
  - repo sync installs management backend requirements with
    `python -m pip install -r backend/requirements.txt`
- Command-line UX must stay low-noise and high-signal:
  - print the active workspace
  - print setup/maintenance completion or failure
  - print a direct recovery command and log path on failure
  - print the exact onboarding/management URL when browser launch is attempted
- Completion-surface bootstrap must be literal:
  - onboarding workflow remains manifest-owned through `workflows.onboarding`
  - management bootstrap resolves Busy + management checkout roots from the
    manifest repository `local_path` entries instead of hard-coded checkout
    names
  - management launch is launcher-owned and must wait for
    `GET /api/health` on the configured local management port before opening the browser
  - management bootstrap failure is a launcher failure and returns non-zero
- Browser launch is **best-effort only**:
  - failure to launch browser/UI must log a warning and still return success when install/repair succeeds
  - when the platform allows it, launcher should bring the relevant browser
    window or an existing matching tab to the foreground instead of opening a
    duplicate background tab

## Threat Notes

- Manifest injection:
  - `wrappers`, repository `local_path`, provider-catalog settings, and
    `post_pull_steps` are authority inputs. They must remain literal and
    reject malformed/coerced values rather than guessing intent.
- Post-pull command trust:
  - `post_pull_steps` is intentionally explicit but still privileged. Reviewers
    should treat changes there as trusted-maintainer execution, not a casual
    convenience surface.
- Wrapper / bin-dir interception:
  - repo-root wrappers and future user-bin shims sit on the command-dispatch
    boundary. PATH/bin-dir precedence and interpreter fallback behavior should
    be reviewed as an authority surface, not only a UX concern.

## Replay / Drift Checks (expected for revalidation)

- Confirm all user-facing entrypoints route to `busy_installer.app`.
- Confirm all user-facing entrypoints bootstrap the repo-local `.venv` before app launch.
- Confirm manifest-driven wrapper policy is honored by all platform entrypoints.
- Confirm spec references still match the current security-critical modules:
  - `busy_installer/core/config.py`
  - `busy_installer/core/runner.py`
  - `busy_installer/platform/launcher.py`
  - `busy_installer/platform/management_bootstrap.py`
- Verify maintenance-first default behavior:
  - no-arg user entrypoints invoke `repair`
  - explicit `install` / `repair` / `status` / `clean` remain available
  - onboarding workflow remains in installer manifest `workflows.onboarding`
- Confirm onboarding-first completion routing:
  - onboarding opens until state becomes `ACTIVE`
  - management opens only after onboarding state is `ACTIVE`
  - management UI root at `http://127.0.0.1:8031` must serve the web app, not only the API
- Confirm browser-open fallback on platforms without opener support.

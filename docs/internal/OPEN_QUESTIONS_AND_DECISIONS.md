# Open Questions And Decisions

This file records the current authority/parsing decisions that are already
intentional, plus the hardening questions that still need explicit resolution.
It exists to satisfy the AGENTS requirement that ambiguous authority boundaries
be tracked somewhere durable instead of inferred from drifted review notes.

## Current Decisions

- CI/CD, GitHub Actions, branch protection, and other automated enforcement
  changes remain blocked on Lynn's explicit approval.
- Manifest authority fields are fail-closed:
  - boolean gates must parse literally
  - list-like command fields such as `post_pull_steps` must remain explicit
  - malformed authority payloads abort manifest load instead of coercing
- Provider-catalog sync is deterministic and visible:
  - remote is attempted first
  - fallback and cache are allowed only as explicit, logged non-remote sources
- Launcher-owned management bootstrap must honor manifest checkout layout
  instead of assuming a bundled path shape.

## Security-Critical Modules

- `busy_installer/core/config.py`
  - Manifest parsing and authority-field validation.
- `busy_installer/core/runner.py`
  - Repository sync, source-of-truth enforcement, provider-catalog selection,
    and step telemetry.
- `busy_installer/platform/launcher.py`
  - User-facing wrapper parsing, lifecycle dispatch, and management bootstrap
    ownership.
- `busy_installer/platform/management_bootstrap.py`
  - Local management runtime ownership, metadata reuse, and browser-root
    readiness gating.

## Open Questions

- Manifest schema strategy:
  - Should the repo add a standalone machine-readable schema for manifests, or
    keep the Python parser as the only authority contract and extend tests
    instead?
- `post_pull_steps` trust boundary:
  - Is the current explicit-list requirement sufficient, or should manifest docs
    also declare `post_pull_steps` as trusted-maintainer-only input with
    stronger repo-allowlist guidance?
- Wrapper/bin-dir threat boundary:
  - Should repo-root wrappers and future user-bin shims be documented together
    as a single security-critical surface, including PATH/bin-dir interception
    risks?
- Adversarial smoke ownership:
  - Which negative-path checks should remain manual in
    `INSTALLER_RELEASE_SMOKE_MATRIX.md`, and which should become repo-owned test
    coverage without violating the no-new-CI rule?

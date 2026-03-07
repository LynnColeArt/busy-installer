# Pillowfort Installer

Primary install path for creating a working Pillowfort/Busy38 system on
Windows, macOS, and Linux.

The platform installer and CLI entrypoints in this repo are the supported
first-time setup path. Other ad-hoc/manual installation flows are legacy
or developer-only.

## Goals

- Shared manifest-driven installation engine
- Deterministic step state (`install-state.json`)
- Canonical-repo mounting for authoritative dependencies
- Local model download staging
- Wrapped onboarding launch and smoke checks

## Quick start

```bash
python -m pip install -e .
pillowfort-installer install --manifest docs/installer-manifest.yaml
```

## Branching

- Default branch is `main`.
- Rename-prep and maintenance PRs should target `main` instead of the historical `master` branch.

## Linux install (primary supported path)

From a local clone of `busy-installer`, run:

```bash
cd /path/to/busy-installer
./busy_installer/platform/linux/launcher.sh
```

Optional environment controls:

- `BUSY_INSTALL_DIR` (install target directory, default: `~/pillowfort`)
- `BUSY_INSTALL_MANIFEST` (manifest override path; default: `docs/installer-manifest.yaml`)
- `BUSY_INSTALL_STRICT_SOURCE=1` (enforce canonical symlink mapping)
- `BUSY_INSTALL_ALLOW_COPY_FALLBACK=1` (permit copied adapter mounts when symlinks unavailable)
- `MANIFEST_UI_OPEN=1` (open local web UI when available)
- `BUSY_INSTALL_ONBOARDING_URL` (override `onboarding_url` from manifest `wrappers`)
- `BUSY_INSTALL_MANAGEMENT_URL` (override `management_url` from manifest `wrappers`)
- `BUSY_INSTALL_SKIP_MODELS=1` (skip model staging during install/re-install)

The launcher runs the local checkout directly and writes logs to
`$BUSY_INSTALL_DIR/busy-installer.log`.

Launcher-owned CLI flags are authoritative when provided:

- `--workspace` overrides `BUSY_INSTALL_DIR`
- `--manifest` overrides `BUSY_INSTALL_MANIFEST`
- relative `--manifest` paths are resolved once up front and reused for both
  launcher reads and the spawned installer process
- launcher-owned flags are parsed once and removed from passthrough so the
  spawned installer command carries one authoritative workspace/manifest value

The launcher also accepts wrapper policy defaults from manifest:

```yaml
wrappers:
  open_management_on_complete: true
  onboarding_url: "http://127.0.0.1:8093"
  management_url: "http://127.0.0.1:8031"
```

`MANIFEST_UI_OPEN`, `BUSY_INSTALL_ONBOARDING_URL`, and `BUSY_INSTALL_MANAGEMENT_URL`
override those manifest values.

Post-install browser routing is onboarding-first:

- if `<workspace>/.busy/onboarding/state.json` is missing or not `ACTIVE`, the
  launcher opens the onboarding surface,
- once onboarding reaches `ACTIVE`, the launcher opens the management surface.

Browser-open failures are logged but do not turn a successful install/repair
into a failed launcher exit.

The bundled manifest now uses explicit installer-owned workflow commands:

- onboarding bootstrap:
  `python -m busy_installer.platform.onboarding_bootstrap --workspace . --busy-root busy-38-ongoing --host 127.0.0.1 --port 8093`
- smoke:
  `python -m busy_installer.platform.onboarding_bootstrap --workspace . --busy-root busy-38-ongoing --host 127.0.0.1 --port 8093 --check-only`

These workflow commands are executed from the install workspace. The installer
runtime prepends the local `busy-installer` checkout to `PYTHONPATH` so the
platform launcher works from a plain repo clone without requiring a separate
editable install first. The onboarding bootstrap command launches the vendored
web app as a detached background process, then returns only after the local
HTTP surface is reachable.

Source-of-truth enforcement is now symlink-first by default:

- required source bindings are remounted to canonical symlinks during install
  and repair,
- copied adapter mounts are only accepted when
  `BUSY_INSTALL_ALLOW_COPY_FALLBACK=1` or the equivalent manifest policy is
  explicitly enabled,
- when explicit copy fallback is enabled and symlink creation fails, installer
  now refreshes the adapter mount from the canonical repo contents instead of
  leaving a placeholder directory behind.

Onboarding bootstrap also fails closed on workspace ownership:

- a reachable `127.0.0.1:8093` listener is reused only when local runtime
  metadata for the current workspace and Busy checkout matches and the recorded
  process is still alive,
- otherwise installer raises an explicit conflict instead of silently trusting
  whichever onboarding process already owns the port.

## macOS and Windows one-click

Run the platform-native entrypoints for a wrapped launch flow:

```bash
./busy_installer/platform/macos/launcher.command
```

```powershell
./busy_installer/platform/windows/launcher.ps1
```

Both shell entrypoints route through `busy_installer.platform.launcher` so behavior is identical:

- manifest-driven config and workspace resolution
- command pass-through support (`install`, `repair`, `status`, `clean`, and passthrough args)
- one-click wrapped management URL open when manifest/ENV policy enables it

```bash
# equivalent explicit mode from the installer repo root
python -m busy_installer.platform.launcher install
```

### Required repositories

The installer manifest marks required repos with `required: true`. If a required
repo fails to sync, the install fails.

The current required set includes:
- `busy38-core`
- `busy38-gticket`
- `busy38-doc-ingest` (mandatory during onboarding/document ingestion setup; adapter mount remains `vendor/busy-38-doc-ingest`)
- `RangeWriter4-a`
- `Blossom`

The manifest also supports an optional provider-catalog block:

```yaml
provider_catalog:
  enabled: true
  required: false
  url: "https://docs.pillowfort.ai/provider-catalog.json"
  cache_path: "provider_catalog.json"
  timeout_seconds: 6
```

When enabled, the installer will download and cache provider metadata before cloning repositories.

If `required: true`, a missing/failed catalog fetch aborts the install unless a valid local cache exists.

If the request fails and the cache already exists, the engine falls back to cache and continues.

Run the CLI in dry-run mode to preview all steps:

```bash
pillowfort-installer install --manifest docs/installer-manifest.yaml --dry-run
```

For the current bundled manifest, local validation should also pass
`--skip-models` or set `BUSY_INSTALL_SKIP_MODELS=1` until the example model
checksum is replaced with a real artifact checksum.

## Commands

- `install`: execute bootstrap workflow
- `repair`: rerun from the last failing step
- `status`: print persisted install state
- `clean`: remove generated install state/reports

## Layout

- `busy_installer/` - runtime engine + CLI
- `docs/installer-manifest.yaml` - manifest example
- `busy_installer/platform/*` - platform wrappers
- `tests/` - unit coverage

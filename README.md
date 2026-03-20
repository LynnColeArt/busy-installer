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
./pillowfort
./pf
./busy
```

That single command bootstraps the repo-local `.venv` if needed, refreshes it
when the repo bootstrap inputs change, runs the maintenance-first installer
flow, and opens the correct first-run surface for the current workspace.

The command line stays intentionally quiet, but it does surface:

- the active workspace path
- whether setup/maintenance succeeded
- the exact recovery command and log path on failure
- the exact onboarding or management URL when a browser needs to be opened or
  reopened manually

Installed console entrypoints also expose the same maintenance-first app
behavior once the package is installed into an environment:

```bash
pf
pillowfort
busy
```

Repo-local Windows front doors are also available as `pf.cmd`,
`pillowfort.cmd`, `busy.cmd`, `pf.ps1`, `pillowfort.ps1`, and `busy.ps1`.

The repo-local `.venv` bootstrap is wrapper-owned. Installed console scripts run
inside the interpreter/environment where `pillowfort-installer` was installed;
they do not create a repo-local `.venv`. The installed `pf` / `busy` /
`pillowfort` console entrypoints now also ship the bundled manifest instead of
depending on a repo-relative `docs/` path that is absent from wheels.

Use the repo bootstrap directly when you want a dev/test environment:

```bash
python3 scripts/bootstrap_env.py --dev
. .venv/bin/activate
```

`scripts/bootstrap_env.py` is now idempotent for unchanged inputs: once
`.venv` is prepared, repeat wrapper launches reuse it until `pyproject.toml` or
`requirements-dev.lock` changes, or until `--dev` is explicitly requested.

Run tests and the bundled-manifest smoke check from that venv:

```bash
python -m pytest -q
python scripts/smoke_manifest.py
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

The platform launchers bootstrap the repo-local `.venv` automatically when
needed, then run the same high-level `busy` / `pillowfort` app path.

Optional environment controls:

- `BUSY_INSTALL_DIR` (install target directory, default: `~/pillowfort`)
- `BUSY_INSTALL_MANIFEST` (manifest override path; default: the bundled installer manifest shipped with the package/repo)
- `BUSY_INSTALL_STRICT_SOURCE=1` (enforce canonical symlink mapping)
- `BUSY_INSTALL_ALLOW_COPY_FALLBACK=1` (permit copied adapter mounts when symlinks unavailable)
- `MANIFEST_UI_OPEN=1` (open local web UI when available)
- `BUSY_INSTALL_ONBOARDING_URL` (override `onboarding_url` from manifest `wrappers`)
- `BUSY_INSTALL_MANAGEMENT_URL` (override `management_url` from manifest `wrappers` when it still targets this machine, such as `localhost`, `127.0.0.1`, `0.0.0.0`, or this machine's hostname/IP)
- `BUSY_INSTALL_SKIP_MODELS=1` (skip model staging during install/re-install)

The launcher runs the local checkout directly and writes logs to
`$BUSY_INSTALL_DIR/busy-installer.log`.

Launcher-owned CLI flags are authoritative when provided:

- `--workspace` overrides `BUSY_INSTALL_DIR`
- `--manifest` overrides `BUSY_INSTALL_MANIFEST`
- launcher subcommand parsing is independent of flag order, so
  `repair --workspace /tmp/ws` and `--workspace /tmp/ws repair` resolve to the
  same authoritative command
- relative `--manifest` paths are resolved once up front and reused for both
  launcher reads and the spawned installer process
- launcher-owned flags are parsed once and removed from passthrough so the
  spawned installer command carries one authoritative workspace/manifest value
- once positional passthrough begins before command authority binds, a later
  valid wrapper subcommand now fails visibly instead of being reinterpreted as
  authoritative launcher intent
- once positional passthrough has begun, later launcher-owned flags now also
  fail visibly instead of mutating wrapper authority after the child boundary
  is already established
- duplicate launcher-owned `--workspace` / `--manifest` assignments now fail
  visibly instead of silently last-winning authority
- multiple wrapper subcommands now fail visibly instead of leaking extra
  command tokens into child passthrough
- manifest-owned wrapper booleans are parsed literally, so quoted values like
  `"false"` fail closed instead of enabling browser-open behavior by truthiness

The launcher also accepts wrapper policy defaults from manifest:

```yaml
wrappers:
  open_management_on_complete: true
  onboarding_url: "http://127.0.0.1:8093"
  management_url: "http://127.0.0.1:8031"
```

`MANIFEST_UI_OPEN`, `BUSY_INSTALL_ONBOARDING_URL`, and `BUSY_INSTALL_MANAGEMENT_URL`
override those manifest values.

Manifest-owned wrapper booleans are parsed literally and fail closed on
malformed values.

Post-install browser routing is onboarding-first:

- if `<workspace>/.busy/onboarding/state.json` is missing or not `ACTIVE`, the
  launcher opens the onboarding surface,
- once onboarding reaches `ACTIVE`, the launcher opens the management surface.

Browser-open failures are logged but do not turn a successful install/repair
into a failed launcher exit. Management bootstrap failures are different: if
the installer cannot bring up the local management surface that owns
`http://127.0.0.1:8031`, launcher exits non-zero instead of opening a dead URL.

When possible, the launcher brings the relevant browser surface to the
foreground instead of just printing a URL. On macOS it also makes a best-effort
attempt to focus an already-open matching tab in supported browsers before
opening a new one.

The bundled manifest now uses explicit installer-owned workflow commands:

- onboarding bootstrap:
  `python -m busy_installer.platform.onboarding_bootstrap --workspace . --busy-root busy-38-ongoing --host 127.0.0.1 --port 8093`
- smoke:
  `python -m busy_installer.platform.onboarding_bootstrap --workspace . --busy-root busy-38-ongoing --host 127.0.0.1 --port 8093 --check-only`

These workflow commands are executed from the install workspace. The installer
runtime prepends the local `busy-installer` checkout to `PYTHONPATH` so the
platform launcher works from a plain repo clone without requiring a separate
editable install first. Manifest-owned bare `python` commands are also
normalized to the interpreter that is currently running the installer, so the
bundled manifest remains portable on hosts that expose `python3` but not a
bare `python` shim. The onboarding bootstrap command launches the vendored web
app as a detached background process, then returns only after the local HTTP
surface is reachable.

Management is now installer-owned too:

- the bundled manifest syncs `busy38-management-ui` into
  `busy-38-ongoing/vendor/busy-38-management-ui`
- until the same-origin browser-root fix is merged on the default
  `busy38-management-ui` branch, the bundled manifest pins that repo to the
  reviewed `fix/installer-management-ui-root` branch so fresh installs remain
  self-consistent
- repo sync installs the management backend requirements into the active
  launcher interpreter with
  `python -m pip install -r backend/requirements.txt`
- once onboarding state is `ACTIVE`, launcher bootstraps the local management
  runtime, waits for `GET /api/health` on `127.0.0.1:8031`, and only then opens
  the management browser surface
- launcher resolves the Busy core and management UI checkout roots from the
  manifest repository `local_path` entries, so custom manifest layouts still
  bootstrap the correct management checkout before browser open
- wildcard management URLs such as `http://0.0.0.0:8031/admin` are normalized
  to a browser-reachable loopback URL before launch, while installer ownership
  checks still probe the same local runtime
- management runtime metadata and health probes now bracket accepted local IPv6
  literals correctly with RFC 3986 host brackets

The installer engine supports symlink-first source-of-truth enforcement:

- when source bindings are marked required or `BUSY_INSTALL_STRICT_SOURCE=1` is
  enabled, adapter mounts are remounted to canonical symlinks during install
  and repair,
- copied adapter mounts are only accepted when
  `BUSY_INSTALL_ALLOW_COPY_FALLBACK=1` or the equivalent manifest policy is
  explicitly enabled,
- when explicit copy fallback is enabled and symlink creation fails, installer
  now refreshes the adapter mount from the canonical repo contents instead of
  leaving a placeholder directory behind.

The bundled manifest keeps those canonical bindings optional so a brand-new
machine does not need pre-existing `~/projects/*` checkouts before the first
`./pillowfort` or `busy` run.

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

Both shell entrypoints route through the same high-level app entrypoint, so behavior is identical:

- dependency bootstrap into the repo-local `.venv`
- maintenance-first command routing (`repair` by default, explicit `install` / `status` / `clean` when requested)
- manifest-driven config and workspace resolution
- one-click wrapped onboarding/management browser open when manifest/ENV policy enables it

```bash
# equivalent explicit mode from the installer repo root
python -m busy_installer.app
```

### Required plugin bootstrap binding checklist

This checklist is scoped to the bundled installer bootstrap flow, not to every
repo or plugin Busy may treat as required in other runtime contexts. If one of
these manifest-owned bootstrap repos or plugin sources fails to sync or mount,
install must fail closed.

The current manifest-owned bootstrap repository set includes:
- `busy38-core`
- `busy38-gticket`
- `busy38-doc-ingest` (mandatory during onboarding/document ingestion setup; adapter mount remains `vendor/busy-38-doc-ingest`)
- `RangeWriter4-a`
- `Blossom`

This list reflects the bundled installer manifest only. It should not be read
as a claim about every Busy runtime required-core ownership boundary outside
installer/bootstrap scope.

The manifest also supports an optional provider-catalog block:

```yaml
provider_catalog:
  enabled: true
  required: false
  url: "https://docs.pillowfort.ai/provider-catalog.json"
  cache_path: "provider_catalog.json"
  fallback_path: "provider-catalog.json"
  timeout_seconds: 6
```

When enabled, the installer will sync provider metadata before repository cloning.

If remote fetch fails, the installer will validate and use the configured
`fallback_path` before trying cache, then fall back to existing cache.
Fallback artifacts are resolved relative to the manifest file location.

If `required: true`, install fails only when all sources (remote, fallback, and cache)
are unavailable or invalid.

If a non-remote source is used (fallback or cache), the step remains successful but
is reported as a warning.

Run the CLI in dry-run mode to preview all steps:

```bash
pillowfort-installer install --manifest docs/installer-manifest.yaml --dry-run
```

The bundled manifest does not stage any default model artifacts. Add model
entries to the manifest only when you have real artifact URLs and checksums to
enforce.

Manifest-owned authority fields fail closed. Use literal YAML booleans (or
explicit `0` / `1`) for flags such as `required`, `enabled`, and
`allow_copy_fallback`. Invalid boolean-like strings and malformed
`post_pull_steps` values now fail manifest load instead of relying on Python
truthiness or implicit coercion.

## Commands

- `repair`: maintenance-first workflow; resumes failed installs when needed and otherwise revalidates/syncs the existing workspace
- `install`: explicit fresh-install style workflow
- `status`: print persisted install state
- `clean`: remove generated install state/reports

## Layout

- `busy_installer/` - runtime engine + CLI
- `docs/installer-manifest.yaml` - manifest example
- `busy_installer/platform/*` - platform wrappers
- `tests/` - unit coverage

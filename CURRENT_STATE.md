# Current State

## 2026-03-19

- Launcher-owned management bootstrap now honors manifest checkout layout:
  - when onboarding state is `ACTIVE`, launcher resolves the Busy core and
    management UI roots from the manifest repository `local_path` entries
    instead of assuming `busy-38-ongoing/vendor/busy-38-management-ui`
  - custom `--manifest` layouts now bootstrap the correct checkout roots before
    opening the management browser surface
- Repo-local bootstrap is now idempotent between unchanged launches:
  - `scripts/bootstrap_env.py` fingerprints `pyproject.toml` and
    `requirements-dev.lock`, records local bootstrap state in `.venv`, and
    reuses the prepared interpreter when those inputs still match
  - runtime wrappers no longer rerun `pip install` on every `pf` / `busy` /
    `pillowfort` launch; they only refresh when the local interpreter is
    missing, bootstrap state is stale/unreadable, dependency inputs changed, or
    `--dev` is explicitly requested
- Windows `.cmd` wrappers now try `python3` first and then bare `python` before
  failing, matching typical Windows Python installs that ship `python.exe`
  without `python3.exe`

## 2026-03-17

- Core manifest parsing now fails closed on ambiguous authority fields:
  - installer booleans are parsed literally, so quoted values like `"false"`
    no longer become truthy through Python coercion.
  - `provider_catalog.timeout_seconds` must be a positive integer.
  - repository `post_pull_steps` must be an explicit YAML list of commands.
- Provider-catalog sync now tolerates the known endpoint instability without losing
  bootstrap determinism:
  - the bundled manifest now points `provider_catalog.fallback_path` to
    `docs/provider-catalog.json`.
  - installer sync now tries remote fetch first, then manifest-local fallback,
    then existing cache before failing when required.
  - valid local fallback payloads are persisted into the workspace cache so future
    runs can continue offline with the same catalog shape.
- `BUSY_INSTALL_SKIP_MODELS` is no longer required for the bundled manifest path:
  - the bundled manifest still ships `models: []`, so default bootstrap no longer
    relies on placeholder checksum gating.

- Repo-root entrypoint wrappers are now hardening-consistent with platform launchers:
  - `pf`, `pillowfort`, and `busy` (and `.cmd`/`.ps1` variants) now prefer an
    existing repo-local venv interpreter for bootstrap when it is executable.
  - Unix wrappers fall back to `python3` when the repo-local venv interpreter
    is unavailable; Windows PowerShell / `.cmd` wrappers try `python3` and then
    bare `python`.
  - After bootstrap runs, wrappers now fail explicitly if `.venv/bin/python` /
    `.venv/Scripts/python.exe` is still missing, instead of silently continuing.

## 2026-03-13

- Management UI startup is now installer-owned instead of best-effort URL
  guessing:
  - the bundled manifest now syncs `busy38-management-ui` into
    `busy-38-ongoing/vendor/busy-38-management-ui`
  - until the same-origin browser-root fix lands on the default
    `busy38-management-ui` branch, the bundled manifest pins that repo to the
    reviewed `fix/installer-management-ui-root` branch so a fresh installer run
    still clones a browser-capable management UI
  - repo sync installs management backend requirements with
    `python -m pip install -r backend/requirements.txt`
  - once onboarding state reaches `ACTIVE`, launcher bootstraps the management
    runtime, waits for `GET /api/health` on `127.0.0.1:8031`, and only then
    opens the browser
  - if management bootstrap fails, launcher exits non-zero instead of opening a
    dead loopback URL
- The repo's plugin-local management UI surface is now test-backed:
  - `ui/manifest.json` declares installer-owned docs/diagnostics sections
  - `ui/actions.py` provides the installer debug action handler for
    `/api/plugins/{plugin_id}/ui/debug`
  - the older Busy roadmap note that listed `busy-installer` as lacking a
    local `/ui` surface is stale relative to this checkout
- Repo-local user entrypoints now exist as `./pf`, `./pillowfort`, and `./busy`
  (plus Windows `.cmd` / PowerShell equivalents), and installed console
  entrypoints now also expose `pf`, `pillowfort`, and `busy`.
  Repo-local wrappers/platform launchers own `.venv` bootstrap; installed
  console scripts run inside the environment where the package is already
  installed.
- The default user-facing path is now maintenance-first:
  - no-arg entrypoints route through `repair`
  - fresh workspaces still complete a full install because `repair` falls back
    to the full install flow when no failed step exists yet
  - existing workspaces now always get a health/update/self-heal pass before
    the onboarding or management surface is reopened
- Platform launchers now prefer the repo-local `.venv` interpreter when it is
  present and only fall back to system Python when the repo venv is absent.
- Platform launchers now bootstrap the repo-local `.venv` automatically before
  launching the high-level app path.
- Launcher console output is now low-noise and high-signal:
  - workspace + lifecycle status are printed directly to the terminal
  - failures print a direct recovery command and log path
  - browser-launch paths print the exact onboarding/management URL
- Browser launch now makes a best-effort foreground/focus pass instead of being
  fire-and-forget only; on macOS supported browsers also get a best-effort
  existing-tab focus attempt before a new tab is opened.
- Local-machine management URL overrides are now broader than pure loopback:
  wildcard bind (`0.0.0.0`) and this machine's hostname/IP now still trigger
  installer-owned management bootstrap instead of silently skipping it.
- The bundled manifest's canonical source bindings are now optional by default,
  so a fresh machine no longer needs pre-existing `~/projects/*` checkouts
  before the first user-facing run succeeds.
- Local bootstrap now has a single repo-owned entrypoint:
  `python3 scripts/bootstrap_env.py`
- The repo now carries a reviewed dependency lock for the local `.venv` path in
  `requirements-dev.lock`.
- A repo-owned smoke harness now exercises the bundled manifest through the
  real high-level app/launcher/CLI dry-run path in an isolated temp workspace and ephemeral
  home directory.
- The repo now also carries a repo-owned release-smoke command plus a manual
  per-OS smoke matrix:
  - `python scripts/release_smoke.py --print-matrix`
  - `python scripts/release_smoke.py --current-platform --skip-bootstrap`
  - CI/workflow automation for this matrix remains deferred pending Lynn Cole's
    involvement.
- The bundled installer manifest no longer ships with a placeholder model
  checksum that forced local validation to pass `--skip-models`.
- Wrapper/platform documentation is now aligned around the actual
  onboarding-first completion routing behavior.

## 2026-03-06

- Installer wrapper browser-launch behavior now routes to the correct first-run
  surface instead of a stale single `8080` default.
- Wrapper selection is now state-driven:
  - onboarding opens when `<workspace>/.busy/onboarding/state.json` is missing
    or not `ACTIVE`
  - management opens only after onboarding state reaches `ACTIVE`
- Default wrapper URLs now align with the current local stack:
  - onboarding: `http://127.0.0.1:8093`
  - management: `http://127.0.0.1:8031`
- Bundled manifest workflow commands now resolve through the Busy checkout in
  the installer workspace using an explicit installer-owned bootstrap helper:
  - `python -m busy_installer.platform.onboarding_bootstrap --workspace . --busy-root busy-38-ongoing --host 127.0.0.1 --port 8093`
  - `python -m busy_installer.platform.onboarding_bootstrap --workspace . --busy-root busy-38-ongoing --host 127.0.0.1 --port 8093 --check-only`
- Workflow commands now prepend the local `busy-installer` checkout to
  `PYTHONPATH` during execution so launcher-driven installs work from a repo
  clone without requiring a separate editable install.
- Manifest-owned bare `python` commands now execute through the interpreter
  that is already running the installer, so the bundled manifest works on
  Ubuntu/Linux hosts that expose `python3` but not a bare `python` shim.
- Onboarding bootstrap now launches the vendored web app in a detached
  background process so the first-run surface remains reachable after the
  installer command exits.
- The bundled manifest now points the required doc-ingest repo at the real
  hosted remote `https://github.com/LynnColeArt/busy38-doc-ingest.git` while
  keeping the Busy adapter mount at `vendor/busy-38-doc-ingest`.
- Installer docs now describe the bundled manifest's required repository set as
  installer/bootstrap scope only, instead of overstating it as the full Busy
  required-core runtime matrix.
- The bundled manifest now also aligns canonical plugin repo remotes with the
  actual hosted sources:
  - RangeWriter -> `https://github.com/LynnColeArt/rangewriter.git`
  - Blossom -> `https://github.com/LynnColeArt/blossom.git`
- Full scratch validation now passes with the bundled manifest:
  - install opens onboarding at `http://127.0.0.1:8093`
  - the onboarding HTTP surface remains reachable after launcher exit
  - repair opens management at `http://127.0.0.1:8031` once onboarding state is
    `ACTIVE`
- The installer engine now enforces the documented symlink-first source-of-truth
  policy when bindings are marked required or strict mode is enabled:
  - required adapter mounts are remounted to canonical symlinks during install
    and repair
  - copied adapter mounts are accepted only when copy fallback is explicitly
    enabled
  - when copy fallback is enabled and symlink creation fails, the installer now
    materializes and refreshes a real adapter copy from the canonical repo
    instead of leaving a placeholder directory behind
- Installer-owned onboarding bootstrap now fails closed on workspace ownership:
  - a reachable onboarding listener is reused only when local runtime metadata
    matches the current workspace/Busy checkout and the recorded PID is still
    alive
  - a foreign process already listening on the configured onboarding port now
    raises an explicit conflict instead of being silently reused
- Browser-open failures remain visible in `busy-installer.log` but no longer
  convert a successful install/repair into a failed launcher exit.
- Launcher workspace/manifest resolution is now single-source and explicit:
  - CLI `--workspace` / `--manifest` override environment defaults inside the
    launcher itself,
  - the launcher subcommand is now parsed independently of flag order, so
    `repair --workspace ...` and `--workspace ... repair` resolve to the same
    authoritative command,
  - launcher-owned long options now bind only when spelled exactly, so
    abbreviations like `--man` and `--work` no longer mutate launcher
    authority silently,
  - launcher-owned parsing now also stops at `--`, so child passthrough can
    fence off launcher-owned flags literally,
  - `--workspace` / `--manifest` now also reject missing or flag-like next
    tokens instead of silently consuming another launcher flag as a path value,
  - once positional passthrough begins before command authority binds, a later
    valid wrapper subcommand now fails visibly instead of being silently
    reinterpreted as launcher authority,
  - once positional passthrough begins, later launcher-owned flags now also
    fail visibly instead of mutating wrapper authority after the child
    boundary has already started,
  - duplicate launcher-owned `--workspace` / `--manifest` assignments now fail
    visibly instead of silently last-winning authority,
  - multiple wrapper subcommands now fail visibly instead of leaking extra
    command tokens into child passthrough,
  - relative manifest paths are canonicalized before wrapper-default reads and
    child installer execution,
  - manifest-owned wrapper booleans are parsed literally so quoted values like
    `"false"` fail closed instead of opening browser surfaces by truthiness,
  - launcher-owned flags are stripped from passthrough before the installer
    command is built,
  - launcher logs, onboarding-state reads, browser routing, and spawned
    installer invocation now use the same resolved workspace.

## Deferred Recommendations

- Add CI coverage for the repo-local `.venv` path across Linux, macOS, and
  Windows so `python -m venv .venv`, `python -m pip install -e '.[dev]'`, and
  `python -m pytest -q` are exercised automatically.
- Do not implement CI or workflow changes in this repo without Lynn Cole's
  involvement. This constraint applies to future CI/workflow decisions across
  repos.

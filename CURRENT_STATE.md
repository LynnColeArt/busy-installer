# Current State

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
- Onboarding bootstrap now launches the vendored web app in a detached
  background process so the first-run surface remains reachable after the
  installer command exits.
- The bundled manifest now points the required doc-ingest repo at the real
  hosted remote `https://github.com/LynnColeArt/busy38-doc-ingest.git` while
  keeping the Busy adapter mount at `vendor/busy-38-doc-ingest`.
- The bundled manifest now also aligns canonical plugin repo remotes with the
  actual hosted sources:
  - RangeWriter -> `https://github.com/LynnColeArt/rangewriter.git`
  - Blossom -> `https://github.com/LynnColeArt/blossom.git`
- Full scratch validation now passes with the bundled manifest when model
  staging is skipped:
  - install opens onboarding at `http://127.0.0.1:8093`
  - the onboarding HTTP surface remains reachable after launcher exit
  - repair opens management at `http://127.0.0.1:8031` once onboarding state is
    `ACTIVE`
- Required source-of-truth bindings now enforce the documented symlink-first
  policy:
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
  - relative manifest paths are canonicalized before wrapper-default reads and
    child installer execution,
  - manifest-owned wrapper booleans are parsed literally so quoted values like
    `"false"` fail closed instead of opening browser surfaces by truthiness,
  - launcher-owned flags are stripped from passthrough before the installer
    command is built,
  - launcher logs, onboarding-state reads, browser routing, and spawned
    installer invocation now use the same resolved workspace.

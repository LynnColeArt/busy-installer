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
- Validation also confirmed one remaining policy gap:
  - required source-of-truth entries still warn when the adapter path is not a
    canonical symlink, instead of failing closed unless copy fallback is
    explicitly enabled
- Browser-open failures remain visible in `busy-installer.log` but no longer
  convert a successful install/repair into a failed launcher exit.

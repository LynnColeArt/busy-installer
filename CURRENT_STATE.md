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
  the installer workspace:
  - `python busy-38-ongoing/busy service setup`
  - `python busy-38-ongoing/busy --help`
- Browser-open failures remain visible in `busy-installer.log` but no longer
  convert a successful install/repair into a failed launcher exit.

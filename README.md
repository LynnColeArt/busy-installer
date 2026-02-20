# Pillowfort Installer

One codebase to install and bootstrap the Pillowfort/Busy38 stack on
Windows, macOS, and Linux.

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

Run in dry-run mode to preview all steps:

```bash
pillowfort-installer install --manifest docs/installer-manifest.yaml --dry-run
```

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

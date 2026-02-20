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

### Required repositories

The installer manifest marks required repos with `required: true`. If a required
repo fails to sync, the install fails.

The current required set includes:
- `busy38-core`
- `busy38-discord`
- `busy38-telegram`
- `busy-38-doc-ingest` (mandatory during onboarding/document ingestion setup)
- `RangeWriter4-a`
- `Blossom`

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

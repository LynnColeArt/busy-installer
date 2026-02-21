import json
from pathlib import Path

import yaml
import pytest

from busy_installer.core.config import InstallerManifest
from busy_installer.core.runner import InstallFailure, InstallerEngine


def test_install_canary_writes_state_and_skips_models(tmp_path: Path) -> None:
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(
        """
version: "1.0"
workspace:
  path: "./workspace"
repositories: []
source_of_truth:
  entries: []
workflows: {}
""",
        encoding="utf-8",
    )
    manifest = InstallerManifest.from_path(manifest_file)
    engine = InstallerEngine(manifest=manifest, workspace=tmp_path / "ws", dry_run=True)
    engine.run(include_models=False)
    assert engine.state.file_path.exists()
    payload = json.loads(engine.state.file_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["manifest"] == manifest_file.name


def test_canonical_fallback_is_rejected_in_strict_mode(tmp_path: Path) -> None:
    manifest = yaml.safe_load("""
version: "1.0"
workspace:
  path: "./workspace"
repositories: []
models: []
source_of_truth:
  allow_copy_fallback: false
  entries:
    - name: RangeWriter4-a
      canonical_path: "~/missing-rw"
      adapter_mount: "busy-38-ongoing/vendor/busy-38-rangewriter"
      required: true
workflows: {}
""")
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    loaded = InstallerManifest.from_path(manifest_file)
    engine = InstallerEngine(
        manifest=loaded,
        workspace=tmp_path / "ws",
        dry_run=True,
        strict_source=True,
    )
    # This test validates strict mode fails when a required canonical source is missing.
    assert len(loaded.source_of_truth.entries) == 1
    with pytest.raises(InstallFailure):
        engine.run(include_models=False)


def test_provider_catalog_step_honors_dry_run(tmp_path: Path) -> None:
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(
        """
version: "1.0"
workspace:
  path: "./workspace"
repositories: []
models: []
provider_catalog:
  enabled: true
  required: true
  url: "https://example.invalid/provider-catalog.json"
  cache_path: "state/provider-catalog.json"
  timeout_seconds: 4
source_of_truth:
  entries: []
workflows: {}
""",
        encoding="utf-8",
    )
    manifest = InstallerManifest.from_path(manifest_file)
    engine = InstallerEngine(
        manifest=manifest,
        workspace=tmp_path / "ws",
        dry_run=True,
    )
    engine.run(include_models=False)

    payload = json.loads(engine.state.file_path.read_text(encoding="utf-8"))
    steps = payload["steps"]
    provider_step = next((item for item in steps if item["name"] == "provider_catalog"), None)
    assert provider_step is not None
    assert provider_step["status"] == "ok"
    assert provider_step["message"] == "Dry-run: catalog fetch skipped"


def test_provider_catalog_validation_warns_on_bad_payload_when_optional(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(
        """
version: "1.0"
workspace:
  path: "."
repositories: []
models: []
provider_catalog:
  enabled: true
  required: false
  url: "https://example.invalid/provider-catalog.json"
  cache_path: "state/provider-catalog.json"
workflows: {}
""",
        encoding="utf-8",
    )
    manifest = InstallerManifest.from_path(manifest_file)
    engine = InstallerEngine(manifest=manifest, workspace=tmp_path / "workspace")

    monkeypatch.setattr(
        "busy_installer.core.runner.InstallerEngine._fetch_provider_catalog",
        lambda *_args, **_kwargs: {"providers": [{"name": "ollama", "models": [{}]}]},
    )

    engine.run(include_models=False)

    payload = json.loads(engine.state.file_path.read_text(encoding="utf-8"))
    provider_step = next(step for step in reversed(payload["steps"]) if step["name"] == "provider_catalog")
    assert provider_step["status"] == "warning"
    assert "failed validation" in provider_step["message"]


def test_provider_catalog_validation_fails_required_without_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(
        """
version: "1.0"
workspace:
  path: "."
repositories: []
models: []
provider_catalog:
  enabled: true
  required: true
  url: "https://example.invalid/provider-catalog.json"
  cache_path: "state/provider-catalog.json"
workflows: {}
""",
        encoding="utf-8",
    )
    manifest = InstallerManifest.from_path(manifest_file)
    engine = InstallerEngine(manifest=manifest, workspace=tmp_path / "workspace")

    monkeypatch.setattr(
        "busy_installer.core.runner.InstallerEngine._fetch_provider_catalog",
        lambda *_args, **_kwargs: {"providers": [{"name": "ollama", "models": [{}]}]},
    )

    with pytest.raises(InstallFailure):
        engine.run(include_models=False)


def test_provider_catalog_validation_uses_existing_cache_when_required_and_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(
        """
version: "1.0"
workspace:
  path: "."
repositories: []
models: []
provider_catalog:
  enabled: true
  required: true
  url: "https://example.invalid/provider-catalog.json"
  cache_path: "state/provider-catalog.json"
workflows: {}
""",
        encoding="utf-8",
    )
    manifest = InstallerManifest.from_path(manifest_file)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cache_path = workspace / "state" / "provider-catalog.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"providers": [{"name": "cached", "models": ["qwen3-0.6b"]}]}),
        encoding="utf-8",
    )

    engine = InstallerEngine(manifest=manifest, workspace=workspace)

    monkeypatch.setattr(
        "busy_installer.core.runner.InstallerEngine._fetch_provider_catalog",
        lambda *_args, **_kwargs: {"providers": [{"name": "ollama", "models": [{}]}]},
    )
    engine.run(include_models=False)

    payload = json.loads(engine.state.file_path.read_text(encoding="utf-8"))
    provider_step = next(step for step in reversed(payload["steps"]) if step["name"] == "provider_catalog")
    assert provider_step["status"] == "warning"

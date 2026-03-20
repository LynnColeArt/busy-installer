import hashlib
import json
import os
import sys
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


def test_required_canonical_binding_replaces_adapter_copy_with_symlink(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical-rw"
    canonical.mkdir(parents=True)
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(
        f"""
version: "1.0"
workspace:
  path: "./workspace"
repositories: []
models: []
source_of_truth:
  allow_copy_fallback: false
  entries:
    - name: RangeWriter4-a
      canonical_path: "{canonical}"
      adapter_mount: "busy-38-ongoing/vendor/busy-38-rangewriter"
      required: true
workflows: {{}}
""",
        encoding="utf-8",
    )
    manifest = InstallerManifest.from_path(manifest_file)
    workspace = tmp_path / "workspace"
    adapter = workspace / "busy-38-ongoing" / "vendor" / "busy-38-rangewriter"
    adapter.mkdir(parents=True, exist_ok=True)
    (adapter / "copied.txt").write_text("copy\n", encoding="utf-8")

    engine = InstallerEngine(manifest=manifest, workspace=workspace)
    engine.run(include_models=False)

    assert adapter.is_symlink()
    assert adapter.resolve() == canonical.resolve()


def test_explicit_copy_fallback_keeps_adapter_copy(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical-rw"
    canonical.mkdir(parents=True)
    (canonical / "canonical.txt").write_text("canonical\n", encoding="utf-8")
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(
        f"""
version: "1.0"
workspace:
  path: "./workspace"
repositories: []
models: []
source_of_truth:
  allow_copy_fallback: true
  entries:
    - name: RangeWriter4-a
      canonical_path: "{canonical}"
      adapter_mount: "busy-38-ongoing/vendor/busy-38-rangewriter"
      required: true
workflows: {{}}
""",
        encoding="utf-8",
    )
    manifest = InstallerManifest.from_path(manifest_file)
    workspace = tmp_path / "workspace"
    adapter = workspace / "busy-38-ongoing" / "vendor" / "busy-38-rangewriter"
    adapter.mkdir(parents=True, exist_ok=True)
    stale_marker = adapter / "stale.txt"
    stale_marker.write_text("stale\n", encoding="utf-8")

    engine = InstallerEngine(
        manifest=manifest,
        workspace=workspace,
        fallback_allowed=True,
    )
    engine.run(include_models=False)

    assert adapter.is_dir()
    assert not adapter.is_symlink()
    assert (adapter / "canonical.txt").read_text(encoding="utf-8") == "canonical\n"
    assert not stale_marker.exists()


def test_explicit_copy_fallback_materializes_adapter_copy_when_symlink_creation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = tmp_path / "canonical-rw"
    canonical.mkdir(parents=True)
    (canonical / "canonical.txt").write_text("canonical\n", encoding="utf-8")
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(
        f"""
version: "1.0"
workspace:
  path: "./workspace"
repositories: []
models: []
source_of_truth:
  allow_copy_fallback: true
  entries:
    - name: RangeWriter4-a
      canonical_path: "{canonical}"
      adapter_mount: "busy-38-ongoing/vendor/busy-38-rangewriter"
      required: true
workflows: {{}}
""",
        encoding="utf-8",
    )
    manifest = InstallerManifest.from_path(manifest_file)
    workspace = tmp_path / "workspace"
    adapter = workspace / "busy-38-ongoing" / "vendor" / "busy-38-rangewriter"

    def fail_symlink(self, target, target_is_directory=False):  # type: ignore[no-untyped-def]
        raise OSError("symlink creation disabled")

    monkeypatch.setattr(Path, "symlink_to", fail_symlink)

    engine = InstallerEngine(
        manifest=manifest,
        workspace=workspace,
        fallback_allowed=True,
    )
    engine.run(include_models=False)

    assert adapter.is_dir()
    assert not adapter.is_symlink()
    assert (adapter / "canonical.txt").read_text(encoding="utf-8") == "canonical\n"


def test_symlink_failure_without_copy_fallback_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = tmp_path / "canonical-rw"
    canonical.mkdir(parents=True)
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(
        f"""
version: "1.0"
workspace:
  path: "./workspace"
repositories: []
models: []
source_of_truth:
  allow_copy_fallback: false
  entries:
    - name: RangeWriter4-a
      canonical_path: "{canonical}"
      adapter_mount: "busy-38-ongoing/vendor/busy-38-rangewriter"
      required: true
workflows: {{}}
""",
        encoding="utf-8",
    )
    manifest = InstallerManifest.from_path(manifest_file)

    def fail_symlink(self, target, target_is_directory=False):  # type: ignore[no-untyped-def]
        raise OSError("symlink creation disabled")

    monkeypatch.setattr(Path, "symlink_to", fail_symlink)

    engine = InstallerEngine(
        manifest=manifest,
        workspace=tmp_path / "workspace",
    )

    with pytest.raises(InstallFailure, match="copy fallback disabled"):
        engine.run(include_models=False)


def test_canonical_binding_accepts_mount_that_already_resolves_to_canonical(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical-rw"
    canonical.mkdir(parents=True)
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(
        f"""
version: "1.0"
workspace:
  path: "./workspace"
repositories: []
models: []
source_of_truth:
  allow_copy_fallback: false
  entries:
    - name: RangeWriter4-a
      canonical_path: "{canonical}"
      adapter_mount: "busy-38-ongoing/vendor/busy-38-rangewriter"
      required: true
workflows: {{}}
""",
        encoding="utf-8",
    )
    manifest = InstallerManifest.from_path(manifest_file)
    workspace = tmp_path / "workspace"
    adapter_mount = workspace / "busy-38-ongoing" / "vendor" / "busy-38-rangewriter"
    adapter_mount.parent.mkdir(parents=True, exist_ok=True)
    adapter_mount.symlink_to(canonical)

    engine = InstallerEngine(manifest=manifest, workspace=workspace)
    engine.run(include_models=False)

    assert adapter_mount.is_symlink()
    assert adapter_mount.resolve() == canonical.resolve()


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
    details = provider_step["details"]
    assert details["candidate_errors"]
    assert any("failed validation" in item for item in details["candidate_errors"])
    assert provider_step["message"] == "No valid provider catalog source available; continuing without catalog update."


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


def test_provider_catalog_uses_manifest_fallback_when_remote_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
  fallback_path: "provider-catalog-fallback.json"
  cache_path: "state/provider-catalog.json"
workflows: {}
""",
        encoding="utf-8",
    )
    (tmp_path / "provider-catalog-fallback.json").write_text(
        json.dumps({"providers": [{"id": "ollama", "name": "Ollama", "models": []}]}),
        encoding="utf-8",
    )

    manifest = InstallerManifest.from_path(manifest_file)
    workspace = tmp_path / "workspace"
    engine = InstallerEngine(manifest=manifest, workspace=workspace)

    monkeypatch.setattr(
        "busy_installer.core.runner.InstallerEngine._fetch_provider_catalog",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("network down")),
    )

    engine.run(include_models=False)

    payload = json.loads(engine.state.file_path.read_text(encoding="utf-8"))
    provider_step = next(step for step in reversed(payload["steps"]) if step["name"] == "provider_catalog")
    assert provider_step["status"] == "warning"
    assert provider_step["message"] == "Using manifest fallback provider catalog"
    assert provider_step["details"]["source"] == "fallback"
    assert provider_step["details"]["candidate_errors"] == ["remote: network down"]
    assert (workspace / "state" / "provider-catalog.json").exists()


def test_provider_catalog_fallback_without_remote_still_warns(tmp_path: Path) -> None:
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
  fallback_path: "provider-catalog-fallback.json"
  cache_path: "state/provider-catalog.json"
workflows: {}
""",
        encoding="utf-8",
    )
    (tmp_path / "provider-catalog-fallback.json").write_text(
        json.dumps({"providers": [{"id": "ollama", "name": "Ollama", "models": []}]}),
        encoding="utf-8",
    )

    manifest = InstallerManifest.from_path(manifest_file)
    workspace = tmp_path / "workspace"
    engine = InstallerEngine(manifest=manifest, workspace=workspace)

    engine.run(include_models=False)

    payload = json.loads(engine.state.file_path.read_text(encoding="utf-8"))
    provider_step = next(step for step in reversed(payload["steps"]) if step["name"] == "provider_catalog")
    assert provider_step["status"] == "warning"
    assert provider_step["message"] == "Using manifest fallback provider catalog"
    assert provider_step["details"]["source"] == "fallback"
    assert "candidate_errors" not in provider_step["details"]
    assert (workspace / "state" / "provider-catalog.json").exists()


def test_provider_catalog_fails_required_when_all_sources_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
  fallback_path: "provider-catalog-fallback.json"
  cache_path: "state/provider-catalog.json"
workflows: {}
""",
        encoding="utf-8",
    )
    (tmp_path / "provider-catalog-fallback.json").write_text(
        json.dumps("invalid", separators=(",", ":")),
        encoding="utf-8",
    )

    manifest = InstallerManifest.from_path(manifest_file)
    engine = InstallerEngine(manifest=manifest, workspace=tmp_path / "workspace")

    monkeypatch.setattr(
        "busy_installer.core.runner.InstallerEngine._fetch_provider_catalog",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("network down")),
    )

    with pytest.raises(InstallFailure):
        engine.run(include_models=False)

    payload = json.loads(engine.state.file_path.read_text(encoding="utf-8"))
    provider_step = next(step for step in reversed(payload["steps"]) if step["name"] == "provider_catalog")
    assert provider_step["status"] == "failed"
    assert "provider catalog unavailable" in provider_step["message"]


def test_model_artifact_source_can_copy_from_local_path(tmp_path: Path) -> None:
    source = tmp_path / "artifacts" / "qwen3.gguf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"model-bytes")
    checksum = hashlib.sha256(b"model-bytes").hexdigest()

    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(
        f"""
version: "1.0"
workspace:
  path: "./workspace"
repositories: []
models:
  - name: qwen3-0.6b
    provider: local
    target_path: "models/qwen3-0.6b"
    files:
      - source: "{source}"
        checksum: "sha256:{checksum}"
source_of_truth:
  entries: []
workflows: {{}}
""",
        encoding="utf-8",
    )
    manifest = InstallerManifest.from_path(manifest_file)
    engine = InstallerEngine(manifest=manifest, workspace=tmp_path / "workspace")
    engine.run(include_models=True)

    staged = tmp_path / "workspace" / "models" / "qwen3-0.6b" / "qwen3.gguf"
    assert staged.exists()
    assert staged.read_bytes() == b"model-bytes"


def test_model_artifact_rejects_bad_checksum(tmp_path: Path) -> None:
    source = tmp_path / "artifacts" / "bad.bin"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"bad-model-bytes")

    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(
        f"""
version: "1.0"
workspace:
  path: "./workspace"
repositories: []
models:
  - name: bad
    provider: local
    target_path: "models/bad"
    files:
      - source: "{source}"
        checksum: "sha256:111111111111111111111111111111111111111111111111111111111111111111"
source_of_truth:
  entries: []
workflows: {{}}
""",
        encoding="utf-8",
    )
    manifest = InstallerManifest.from_path(manifest_file)
    engine = InstallerEngine(manifest=manifest, workspace=tmp_path / "workspace")

    with pytest.raises(InstallFailure):
        engine.run(include_models=True)


def test_repair_resumes_from_failed_phase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(
        """
version: "1.0"
workspace:
  path: "./workspace"
repositories: []
models: []
source_of_truth:
  entries: []
workflows:
  onboarding:
    command: ""
""",
        encoding="utf-8",
    )
    manifest = InstallerManifest.from_path(manifest_file)

    engine = InstallerEngine(manifest=manifest, workspace=tmp_path / "workspace")
    phase_calls: list[str] = []
    state = {"fail_onboarding_once": True}

    orig_precheck = engine._precheck
    orig_workspace = engine._bootstrap_workspace
    orig_onboarding = engine._run_onboarding
    orig_smoke = engine._run_smoke

    def _wrapped_precheck() -> None:
        phase_calls.append("precheck")
        orig_precheck()

    def _wrapped_workspace() -> None:
        phase_calls.append("workspace")
        orig_workspace()

    def _wrapped_onboarding() -> None:
        phase_calls.append("onboarding")
        if state["fail_onboarding_once"]:
            state["fail_onboarding_once"] = False
            raise InstallFailure("simulated onboarding failure")
        orig_onboarding()

    def _wrapped_smoke() -> None:
        phase_calls.append("smoke")
        orig_smoke()

    monkeypatch.setattr(engine, "_precheck", _wrapped_precheck)
    monkeypatch.setattr(engine, "_bootstrap_workspace", _wrapped_workspace)
    monkeypatch.setattr(engine, "_run_onboarding", _wrapped_onboarding)
    monkeypatch.setattr(engine, "_run_smoke", _wrapped_smoke)

    with pytest.raises(InstallFailure):
        engine.run()

    assert phase_calls.count("precheck") == 1
    assert phase_calls.count("workspace") == 1
    assert phase_calls.count("onboarding") == 1
    assert phase_calls.count("smoke") == 0

    engine.run(resume=True)

    assert phase_calls.count("precheck") == 1
    assert phase_calls.count("workspace") == 1
    assert phase_calls.count("onboarding") == 2
    assert phase_calls.count("smoke") == 1

    payload = json.loads(engine.state.file_path.read_text(encoding="utf-8"))
    assert payload["steps"][-1]["name"] == "finalize"
    assert payload["steps"][-1]["status"] == "ok"


def test_workflow_commands_prepend_installer_repo_root_to_pythonpath(tmp_path: Path) -> None:
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(
        """
version: "1.0"
workspace:
  path: "./workspace"
repositories: []
models: []
source_of_truth:
  entries: []
workflows:
  onboarding:
    command: "python -m busy_installer.platform.onboarding_bootstrap --workspace . --busy-root busy-38-ongoing --check-only"
  smoke:
    command: "python -m busy_installer.platform.onboarding_bootstrap --workspace . --busy-root busy-38-ongoing --check-only"
""",
        encoding="utf-8",
    )
    manifest = InstallerManifest.from_path(manifest_file)
    observed_pythonpaths: list[str | None] = []
    original_pythonpath = os.environ.get("PYTHONPATH")

    def fake_runner(command: list[str], cwd: Path) -> int:
        observed_pythonpaths.append(os.environ.get("PYTHONPATH"))
        return 0

    engine = InstallerEngine(
        manifest=manifest,
        workspace=tmp_path / "workspace",
        command_runner=fake_runner,
    )

    engine.run(include_models=False)

    installer_root = str(Path(__file__).resolve().parents[1])
    assert len(observed_pythonpaths) == 2
    assert all(value is not None for value in observed_pythonpaths)
    assert all(value.split(os.pathsep)[0] == installer_root for value in observed_pythonpaths if value)
    assert os.environ.get("PYTHONPATH") == original_pythonpath


def test_manifest_python_commands_reuse_current_interpreter(tmp_path: Path) -> None:
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(
        """
version: "1.0"
workspace:
  path: "./workspace"
repositories:
  - name: busy38-core
    url: "https://example.com/Busy.git"
    branch: "main"
    local_path: "busy-38-ongoing"
    required: true
    post_pull_steps:
      - "python -m pip install -r requirements.txt"
models: []
source_of_truth:
  entries: []
workflows:
  onboarding:
    command: "python -m busy_installer.platform.onboarding_bootstrap --workspace . --busy-root busy-38-ongoing --check-only"
  smoke:
    command: "python -m busy_installer.platform.onboarding_bootstrap --workspace . --busy-root busy-38-ongoing --check-only"
""",
        encoding="utf-8",
    )
    manifest = InstallerManifest.from_path(manifest_file)
    workspace = tmp_path / "workspace"
    repo_root = workspace / "busy-38-ongoing"
    repo_root.mkdir(parents=True)
    (repo_root / ".git").mkdir()
    observed_commands: list[list[str]] = []

    def fake_runner(command: list[str], cwd: Path) -> int:
        observed_commands.append(command)
        return 0

    engine = InstallerEngine(
        manifest=manifest,
        workspace=workspace,
        command_runner=fake_runner,
    )

    engine.run(include_models=False)

    python_commands = [command for command in observed_commands if command and command[0] == sys.executable]
    assert len(python_commands) == 3
    assert python_commands[0][:4] == [sys.executable, "-m", "pip", "install"]
    assert python_commands[1][:3] == [
        sys.executable,
        "-m",
        "busy_installer.platform.onboarding_bootstrap",
    ]
    assert python_commands[2][:3] == [
        sys.executable,
        "-m",
        "busy_installer.platform.onboarding_bootstrap",
    ]

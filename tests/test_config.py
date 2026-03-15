from pathlib import Path

import yaml

from busy_installer.core.config import InstallerManifest


def test_manifest_loads_with_workspace_and_source_mappings(tmp_path: Path) -> None:
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(
        """
version: "1.0"
workspace:
  path: "./workspace"
repositories: []
models: []
source_of_truth:
  allow_copy_fallback: true
  entries:
    - name: RangeWriter4-a
      canonical_path: "~/canons/rw4"
      adapter_mount: "busy-38-ongoing/vendor/busy-38-rangewriter"
      required: true
""",
        encoding="utf-8",
    )
    manifest = InstallerManifest.from_path(manifest_file)
    assert manifest.version == "1.0"
    assert manifest.source_of_truth.allow_copy_fallback is True
    assert manifest.workspace.exists() is False
    bindings = list(manifest.canonical_bindings())
    assert len(bindings) == 1
    assert bindings[0].name == "RangeWriter4-a"


def test_manifest_loads_provider_catalog_block(tmp_path: Path) -> None:
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(
        """
version: "1.0"
workspace:
  path: "./workspace"
provider_catalog:
  enabled: true
  required: true
  url: "https://example.invalid/provider-catalog.json"
  cache_path: "state/provider-catalog.json"
  timeout_seconds: 4
repositories: []
models: []
source_of_truth:
  entries: []
""",
        encoding="utf-8",
    )
    manifest = InstallerManifest.from_path(manifest_file)
    assert manifest.provider_catalog.enabled is True
    assert manifest.provider_catalog.required is True
    assert manifest.provider_catalog.url == "https://example.invalid/provider-catalog.json"
    assert manifest.provider_catalog.cache_path == "state/provider-catalog.json"
    assert manifest.provider_catalog.timeout_seconds == 4


def test_bundled_manifest_uses_onboarding_bootstrap_helper_and_current_ports() -> None:
    manifest_path = Path(__file__).resolve().parents[1] / "docs" / "installer-manifest.yaml"
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))

    workflows = payload["workflows"]
    models = payload["models"]
    wrappers = payload["wrappers"]
    core_repo = next(repo for repo in payload["repositories"] if repo["name"] == "busy38-core")
    doc_ingest_repo = next(repo for repo in payload["repositories"] if repo["name"] == "busy38-doc-ingest")
    management_repo = next(repo for repo in payload["repositories"] if repo["name"] == "busy38-management-ui")
    rangewriter_repo = next(repo for repo in payload["repositories"] if repo["name"] == "RangeWriter4-a")
    blossom_repo = next(repo for repo in payload["repositories"] if repo["name"] == "Blossom")

    assert (
        workflows["onboarding"]["command"]
        == "python -m busy_installer.platform.onboarding_bootstrap --workspace . --busy-root busy-38-ongoing --host 127.0.0.1 --port 8093"
    )
    assert (
        workflows["smoke"]["command"]
        == "python -m busy_installer.platform.onboarding_bootstrap --workspace . --busy-root busy-38-ongoing --host 127.0.0.1 --port 8093 --check-only"
    )
    assert models == []
    assert wrappers["onboarding_url"] == "http://127.0.0.1:8093"
    assert wrappers["management_url"] == "http://127.0.0.1:8031"
    assert core_repo["post_pull_steps"] == ["python -m pip install -r requirements.txt"]
    assert doc_ingest_repo["url"] == "https://github.com/LynnColeArt/busy38-doc-ingest.git"
    assert doc_ingest_repo["local_path"] == "busy-38-ongoing/vendor/busy-38-doc-ingest"
    assert management_repo["url"] == "https://github.com/LynnColeArt/busy38-management-ui.git"
    assert management_repo["branch"] == "fix/installer-management-ui-root"
    assert management_repo["local_path"] == "busy-38-ongoing/vendor/busy-38-management-ui"
    assert management_repo["post_pull_steps"] == ["python -m pip install -r backend/requirements.txt"]
    assert rangewriter_repo["url"] == "https://github.com/LynnColeArt/rangewriter.git"
    assert blossom_repo["url"] == "https://github.com/LynnColeArt/blossom.git"

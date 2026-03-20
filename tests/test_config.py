from pathlib import Path

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

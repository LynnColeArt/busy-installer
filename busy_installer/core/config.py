from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml


def _parse_manifest_bool(value: Any, *, field_name: str) -> bool:
    # Manifest booleans gate required repos, catalog sync, and copy fallback.
    # Parse them literally so quoted "false" never becomes truthy.
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    raise ValueError(f"{field_name} must be a literal boolean")


def _parse_positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = int(value.strip())
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an integer") from exc
    else:
        raise ValueError(f"{field_name} must be an integer")
    if parsed <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return parsed


def _parse_command_steps(value: Any, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be a list of commands")
    steps: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field_name}[{index}] must be a non-empty string")
        steps.append(item)
    return tuple(steps)


@dataclass(frozen=True)
class RepositoryConfig:
    name: str
    url: str
    local_path: str
    branch: str = "main"
    required: bool = False
    canonical_only: bool = False
    post_pull_steps: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "RepositoryConfig":
        if not isinstance(value, dict):
            raise ValueError("Repository entry must be a mapping")
        if "name" not in value or "url" not in value or "local_path" not in value:
            raise ValueError("Repository entry requires name, url, and local_path")
        return cls(
            name=str(value["name"]),
            url=str(value["url"]),
            local_path=str(value["local_path"]),
            branch=str(value.get("branch", "main")),
            required=_parse_manifest_bool(value.get("required", False), field_name="repositories[].required"),
            canonical_only=_parse_manifest_bool(
                value.get("canonical_only", False),
                field_name="repositories[].canonical_only",
            ),
            post_pull_steps=_parse_command_steps(
                value.get("post_pull_steps", ()),
                field_name="repositories[].post_pull_steps",
            ),
        )


@dataclass(frozen=True)
class SourceBinding:
    name: str
    canonical_path: str
    adapter_mount: str
    required: bool = False

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "SourceBinding":
        if not isinstance(value, dict):
            raise ValueError("Source binding entry must be a mapping")
        if "name" not in value or "canonical_path" not in value or "adapter_mount" not in value:
            raise ValueError("Source binding requires name, canonical_path, and adapter_mount")
        return cls(
            name=str(value["name"]),
            canonical_path=str(value["canonical_path"]),
            adapter_mount=str(value["adapter_mount"]),
            required=_parse_manifest_bool(value.get("required", False), field_name="source_of_truth.entries[].required"),
        )


@dataclass(frozen=True)
class ModelArtifact:
    source: str
    checksum: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "ModelArtifact":
        if not isinstance(value, dict):
            raise ValueError("Model artifact entry must be a mapping")
        return cls(
            source=str(value["source"]),
            checksum=value.get("checksum"),
        )


@dataclass(frozen=True)
class ModelConfig:
    name: str
    provider: str
    target_path: str
    files: tuple[ModelArtifact, ...]

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "ModelConfig":
        if not isinstance(value, dict):
            raise ValueError("Model config entry must be a mapping")
        files = value.get("files")
        if not isinstance(files, (list, tuple)) or not files:
            raise ValueError(f"Model config {value.get('name')} requires files")
        return cls(
            name=str(value.get("name")),
            provider=str(value.get("provider", "local")),
            target_path=str(value.get("target_path", "")),
            files=tuple(ModelArtifact.from_mapping(item) for item in files),
        )


@dataclass(frozen=True)
class ProviderCatalogConfig:
    enabled: bool = False
    required: bool = False
    url: str = ""
    cache_path: str = "provider-catalog.json"
    timeout_seconds: int = 6
    fallback_path: str = ""

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> "ProviderCatalogConfig":
        if not value:
            return cls()
        if not isinstance(value, dict):
            raise ValueError("provider_catalog must be a mapping")
        return cls(
            enabled=_parse_manifest_bool(value.get("enabled", False), field_name="provider_catalog.enabled"),
            required=_parse_manifest_bool(value.get("required", False), field_name="provider_catalog.required"),
            url=str(value.get("url", "")),
            cache_path=str(value.get("cache_path", "provider-catalog.json")),
            timeout_seconds=_parse_positive_int(value.get("timeout_seconds", 6), field_name="provider_catalog.timeout_seconds"),
            fallback_path=str(value.get("fallback_path", "")),
        )


@dataclass(frozen=True)
class WorkflowConfig:
    command: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> "WorkflowConfig":
        if not value:
            return cls()
        if not isinstance(value, dict):
            raise ValueError("workflow entries must be mappings")
        return cls(command=value.get("command"))


@dataclass(frozen=True)
class SourceOfTruthConfig:
    allow_copy_fallback: bool = False
    entries: tuple[SourceBinding, ...] = ()

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> "SourceOfTruthConfig":
        if not value:
            return cls()
        if not isinstance(value, dict):
            raise ValueError("source_of_truth must be a mapping")
        entries = value.get("entries", ())
        if not isinstance(entries, (list, tuple)):
            raise ValueError("source_of_truth.entries must be a list")
        return cls(
            allow_copy_fallback=_parse_manifest_bool(
                value.get("allow_copy_fallback", False),
                field_name="source_of_truth.allow_copy_fallback",
            ),
            entries=tuple(SourceBinding.from_mapping(item) for item in entries),
        )


@dataclass(frozen=True)
class InstallerManifest:
    version: str
    path: Path
    repositories: tuple[RepositoryConfig, ...]
    models: tuple[ModelConfig, ...]
    source_of_truth: SourceOfTruthConfig
    provider_catalog: ProviderCatalogConfig
    onboarding: WorkflowConfig
    smoke: WorkflowConfig
    workspace_path: str | None
    description: str | None = None

    @property
    def workspace(self) -> Path:
        if self.workspace_path:
            return Path(self.workspace_path).expanduser().resolve()
        return Path.cwd()

    def canonical_bindings(self) -> Iterable[SourceBinding]:
        return self.source_of_truth.entries

    @classmethod
    def from_path(cls, path: str | Path) -> "InstallerManifest":
        manifest_path = Path(path).expanduser().resolve()
        with manifest_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError("manifest must be a YAML object")
        repositories_value = data.get("repositories", ())
        if not isinstance(repositories_value, (list, tuple)):
            raise ValueError("manifest.repositories must be a list")
        models_value = data.get("models", ())
        if not isinstance(models_value, (list, tuple)):
            raise ValueError("manifest.models must be a list")
        repositories = tuple(RepositoryConfig.from_mapping(item) for item in repositories_value)
        models = tuple(ModelConfig.from_mapping(item) for item in models_value)
        wrapper = data.get("source_of_truth", {})
        workflows = data.get("workflows", {})
        return cls(
            version=str(data.get("version", "0")),
            path=manifest_path,
            description=data.get("description"),
            repositories=repositories,
            models=models,
            source_of_truth=SourceOfTruthConfig.from_mapping(wrapper),
            provider_catalog=ProviderCatalogConfig.from_mapping(data.get("provider_catalog")),
            onboarding=WorkflowConfig.from_mapping(workflows.get("onboarding")),
            smoke=WorkflowConfig.from_mapping(workflows.get("smoke")),
            workspace_path=data.get("workspace", {}).get("path") if isinstance(data.get("workspace"), dict) else None,
        )

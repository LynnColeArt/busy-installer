from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml


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
        if "name" not in value or "url" not in value or "local_path" not in value:
            raise ValueError("Repository entry requires name, url, and local_path")
        return cls(
            name=str(value["name"]),
            url=str(value["url"]),
            local_path=str(value["local_path"]),
            branch=str(value.get("branch", "main")),
            required=bool(value.get("required", False)),
            canonical_only=bool(value.get("canonical_only", False)),
            post_pull_steps=tuple(value.get("post_pull_steps", ())),
        )


@dataclass(frozen=True)
class SourceBinding:
    name: str
    canonical_path: str
    adapter_mount: str
    required: bool = False

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "SourceBinding":
        if "name" not in value or "canonical_path" not in value or "adapter_mount" not in value:
            raise ValueError("Source binding requires name, canonical_path, and adapter_mount")
        return cls(
            name=str(value["name"]),
            canonical_path=str(value["canonical_path"]),
            adapter_mount=str(value["adapter_mount"]),
            required=bool(value.get("required", False)),
        )


@dataclass(frozen=True)
class ModelArtifact:
    source: str
    checksum: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "ModelArtifact":
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
        files = value.get("files")
        if not files:
            raise ValueError(f"Model config {value.get('name')} requires files")
        return cls(
            name=str(value.get("name")),
            provider=str(value.get("provider", "local")),
            target_path=str(value.get("target_path", "")),
            files=tuple(ModelArtifact.from_mapping(item) for item in files),
        )


@dataclass(frozen=True)
class WorkflowConfig:
    command: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> "WorkflowConfig":
        if not value:
            return cls()
        return cls(command=value.get("command"))


@dataclass(frozen=True)
class SourceOfTruthConfig:
    allow_copy_fallback: bool = False
    entries: tuple[SourceBinding, ...] = ()

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> "SourceOfTruthConfig":
        if not value:
            return cls()
        return cls(
            allow_copy_fallback=bool(value.get("allow_copy_fallback", False)),
            entries=tuple(SourceBinding.from_mapping(item) for item in value.get("entries", ())),
        )


@dataclass(frozen=True)
class InstallerManifest:
    version: str
    path: Path
    repositories: tuple[RepositoryConfig, ...]
    models: tuple[ModelConfig, ...]
    source_of_truth: SourceOfTruthConfig
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
        repositories = tuple(RepositoryConfig.from_mapping(item) for item in data.get("repositories", ()))
        models = tuple(ModelConfig.from_mapping(item) for item in data.get("models", ()))
        wrapper = data.get("source_of_truth", {})
        workflows = data.get("workflows", {})
        return cls(
            version=str(data.get("version", "0")),
            path=manifest_path,
            description=data.get("description"),
            repositories=repositories,
            models=models,
            source_of_truth=SourceOfTruthConfig.from_mapping(wrapper),
            onboarding=WorkflowConfig.from_mapping(workflows.get("onboarding")),
            smoke=WorkflowConfig.from_mapping(workflows.get("smoke")),
            workspace_path=data.get("workspace", {}).get("path") if isinstance(data.get("workspace"), dict) else None,
        )


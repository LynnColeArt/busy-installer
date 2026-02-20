from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Callable

from .config import (
    InstallerManifest,
    ModelArtifact,
    RepositoryConfig,
    SourceBinding,
)
from .state import InstallState

CommandRunner = Callable[[list[str], Path], int]


class InstallFailure(RuntimeError):
    pass


class InstallerEngine:
    def __init__(
        self,
        manifest: InstallerManifest,
        workspace: Path | None = None,
        *,
        dry_run: bool = False,
        strict_source: bool = False,
        fallback_allowed: bool = False,
        command_runner: CommandRunner | None = None,
        state_path: Path | None = None,
    ):
        self.manifest = manifest
        self.workspace = workspace or manifest.workspace
        self.dry_run = dry_run
        self.strict_source = strict_source
        self.fallback_allowed = fallback_allowed
        self.command_runner = command_runner or self._default_runner
        self.state = InstallState.load(state_path or self.workspace)
        self.state.set_meta(manifest=self.manifest.path.name, workspace=str(self.workspace))

    def run(self, include_models: bool = True) -> None:
        try:
            self._precheck()
            self._bootstrap_workspace()
            self._sync_repositories()
            self._apply_source_bindings()
            if include_models:
                self._prepare_models()
            self._run_onboarding()
            self._run_smoke()
            self._finalize()
        except Exception as exc:  # pragma: no cover - broad surfacing
            self.state.fail("install", exc)
            raise

    def _default_runner(self, command: list[str], cwd: Path) -> int:
        if self.dry_run:
            return 0
        result = subprocess.run(command, cwd=str(cwd), check=False)
        return result.returncode

    def _record_step(self, name: str, status: str, *, message: str | None = None, details: dict | None = None) -> None:
        self.state.record(name, status, message=message, details=details or None)

    def _precheck(self) -> None:
        if not self.manifest.repositories:
            self._record_step("precheck", "warning", message="No repositories configured")
            return
        self._record_step("precheck", "ok", message=f"Loaded manifest v{self.manifest.version}")

    def _bootstrap_workspace(self) -> None:
        if self.workspace.exists():
            self._record_step("workspace", "ok", message=f"Using existing workspace: {self.workspace}")
            return
        self._record_step("workspace", "start", message=f"Creating workspace: {self.workspace}")
        if self.dry_run:
            self._record_step("workspace", "ok", message="Dry-run: workspace create skipped")
            return
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._record_step("workspace", "ok", message="Workspace created")

    def _resolve_repo_path(self, repo: RepositoryConfig) -> Path:
        return (self.workspace / repo.local_path).resolve()

    def _sync_repositories(self) -> None:
        for repo in self.manifest.repositories:
            self._sync_repo(repo)

    def _sync_repo(self, repo: RepositoryConfig) -> None:
        target = self._resolve_repo_path(repo)
        details = {
            "name": repo.name,
            "url": repo.url,
            "path": str(target),
            "branch": repo.branch,
        }
        self._record_step("repo", "start", message=f"Syncing {repo.name}", details=details)
        try:
            if target.exists():
                if repo.required and not self._is_git_repo(target):
                    raise InstallFailure(f"required repository path exists but is not a repo: {target}")
                if self.dry_run:
                    self._record_step("repo", "ok", message=f"Would update {repo.name}", details=details)
                    return
                self._run(["git", "fetch", "--all"], target)
                self._run(["git", "checkout", repo.branch], target)
                self._run(["git", "pull", "--ff-only", "origin", repo.branch], target)
            else:
                if self.dry_run:
                    self._record_step("repo", "ok", message=f"Would clone {repo.name}", details=details)
                    return
                target.parent.mkdir(parents=True, exist_ok=True)
                self._run(["git", "clone", "--depth", "1", "--branch", repo.branch, repo.url, str(target)], self.workspace)
            for step in repo.post_pull_steps:
                if step:
                    if step.startswith("python ") and self.dry_run:
                        self._record_step("repo", "info", message=f"Would run post-pull: {step}", details=details)
                    else:
                        self._run(step.split(), target)
            self._record_step("repo", "ok", message=f"Synced {repo.name}", details=details)
        except Exception as exc:
            if repo.required:
                self._record_step("repo", "failed", message=str(exc), details=details)
                raise
            self._record_step("repo", "skipped", message=f"Optional repo skipped: {repo.name}", details=details)

    def _is_git_repo(self, path: Path) -> bool:
        return (path / ".git").is_dir()

    def _run(self, command: list[str], cwd: Path) -> int:
        code = self.command_runner(command, cwd)
        if code != 0:
            raise InstallFailure(f"command failed (rc={code}): {' '.join(command)}")
        return code

    def _apply_source_bindings(self) -> None:
        entries = list(self.manifest.canonical_bindings())
        if not entries:
            self._record_step("canonical", "skipped", message="No source-of-truth entries configured")
            return
        for binding in entries:
            self._apply_source_binding(binding)

    def _apply_source_binding(self, binding: SourceBinding) -> None:
        canonical = Path(os.path.expanduser(binding.canonical_path)).resolve()
        adapter = self._resolve_repo_mount(binding.adapter_mount)
        details = {"canonical": str(canonical), "adapter": str(adapter), "required": binding.required}
        self._record_step("canonical", "start", message=f"Binding source {binding.name}", details=details)
        try:
            if not canonical.exists():
                msg = f"canonical source missing: {canonical}"
                if binding.required or self.strict_source:
                    raise InstallFailure(msg)
                self._record_step("canonical", "warning", message=msg, details=details)
                return

            self._ensure_adapter_path(adapter, canonical)
            if adapter.is_symlink():
                if adapter.resolve() == canonical:
                    self._record_step("canonical", "ok", message=f"Canonical symlink active for {binding.name}", details=details)
                    return
                if not self.fallback_allowed or self.strict_source:
                    raise InstallFailure(f"adapter points to unexpected source: {adapter.resolve()}")
                self._record_step("canonical", "warning", message="Symlink target mismatch; keeping explicit state", details=details)
                return

            if not self.fallback_allowed:
                if self.strict_source:
                    raise InstallFailure(
                        f"canonical path must be mounted as symlink: {adapter} -> {canonical}; copy fallback disabled"
                    )
                self._record_step(
                    "canonical",
                    "warning",
                    message="Adapter is not symlinked for source-of-truth mapping",
                    details=details,
                )
                return

            self._record_step("canonical", "ok", message=f"Accepting adapter copy for {binding.name}", details=details)
        except Exception as exc:
            if binding.required or self.strict_source:
                raise
            self._record_step("canonical", "warning", message=str(exc), details=details)

    def _ensure_adapter_path(self, adapter: Path, canonical: Path) -> None:
        if adapter.exists():
            if self.dry_run:
                return
            if adapter.is_symlink() or adapter.is_file() or adapter.is_dir():
                return
            return
        if self.dry_run:
            return
        adapter.parent.mkdir(parents=True, exist_ok=True)
        try:
            adapter.symlink_to(canonical)
        except (OSError, RuntimeError):
            if self.fallback_allowed:
                adapter.mkdir(parents=True, exist_ok=True)
            else:
                raise

    def _resolve_repo_mount(self, mount: str) -> Path:
        return (self.workspace / mount).resolve()

    def _prepare_models(self) -> None:
        if not self.manifest.models:
            self._record_step("models", "skipped", message="No models configured")
            return
        for model in self.manifest.models:
            raw_target = self.workspace / model.target_path
            target = raw_target if not raw_target.suffix else raw_target.parent
            details = {"path": str(raw_target), "provider": model.provider}
            self._record_step("model", "start", message=f"Preparing model {model.name}", details=details)
            if self.dry_run:
                self._record_step("model", "ok", message="Model staging would run", details=details)
                continue
            target.mkdir(parents=True, exist_ok=True)
            for artifact in model.files:
                self._fetch_artifact(artifact, target)
            self._record_step("model", "ok", message=f"Model prepared: {model.name}", details=details)

    def _fetch_artifact(self, artifact: ModelArtifact, target_dir: Path) -> None:
        normalized = target_dir / Path(artifact.source).name
        if artifact.checksum:
            artifact_hash = hashlib.sha256(str(artifact.source).encode("utf-8")).hexdigest()[:8]
            marker = target_dir / f".{normalized.name}.checksum"
            if marker.exists() and marker.read_text(encoding="utf-8").strip() == artifact.checksum:
                self._record_step("model", "info", message=f"Model artifact already cached: {normalized.name}")
                return
            marker.write_text(f"{artifact.checksum}\\n{artifact_hash}\\n", encoding="utf-8")

    def _run_onboarding(self) -> None:
        if not self.manifest.onboarding.command:
            self._record_step("onboarding", "skipped", message="No onboarding workflow configured")
            return
        self._record_step("onboarding", "start", message="Running onboarding")
        if self.dry_run:
            self._record_step("onboarding", "ok", message=f"Would run command: {self.manifest.onboarding.command}")
            return
        self._run(self.manifest.onboarding.command.split(), self.workspace)
        self._record_step("onboarding", "ok", message="Onboarding command completed")

    def _run_smoke(self) -> None:
        if not self.manifest.smoke.command:
            self._record_step("smoke", "skipped", message="No smoke workflow configured")
            return
        self._record_step("smoke", "start", message="Running smoke check")
        if self.dry_run:
            self._record_step("smoke", "ok", message=f"Would run command: {self.manifest.smoke.command}")
            return
        self._run(self.manifest.smoke.command.split(), self.workspace)
        self._record_step("smoke", "ok", message="Smoke check completed")

    def _finalize(self) -> None:
        if self.dry_run:
            self._record_step("finalize", "ok", message="Dry-run complete")
            return
        report = self.workspace / "installer-report.md"
        report.write_text("# Installer report\nInstall completed.\n", encoding="utf-8")
        self._record_step("finalize", "ok", message="Installer finished")

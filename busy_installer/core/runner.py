from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import string
import sys
import urllib.parse
import urllib.request
import shlex
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, List

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

    def run(self, include_models: bool = True, *, resume: bool = False) -> None:
        phase_order = [
            "precheck",
            "workspace",
            "provider_catalog",
            "repo",
            "canonical",
            "models",
            "onboarding",
            "smoke",
            "finalize",
        ]

        try:
            resume_from = self._resolve_resume_start(resume)
            start_index = phase_order.index(resume_from) if resume_from in phase_order else 0

            if resume:
                self._record_step(
                    "install",
                    "resume",
                    message=f"Resuming install from phase '{resume_from or 'precheck'}'",
                    details={"requested": True, "from_phase": resume_from or "precheck"},
                )

            self._run_phase("precheck", self._precheck, start=start_index == 0)
            self._run_phase("workspace", self._bootstrap_workspace, start=start_index <= 1)
            self._run_phase("provider_catalog", self._sync_provider_catalog, start=start_index <= 2)
            self._run_phase("repo", self._sync_repositories, start=start_index <= 3)
            self._run_phase("canonical", self._apply_source_bindings, start=start_index <= 4)
            if include_models:
                self._run_phase("models", self._prepare_models, start=start_index <= 5)
            self._run_phase("onboarding", self._run_onboarding, start=start_index <= 6)
            self._run_phase("smoke", self._run_smoke, start=start_index <= 7)
            self._run_phase("finalize", self._finalize, start=start_index <= 8)
        except Exception as exc:  # pragma: no cover - broad surfacing
            if self.state.last_failed_step_name(exclude_install=True) is None:
                self.state.fail("install", exc)
            raise

    def _run_phase(self, phase_name: str, phase: Callable[[], None], *, start: bool) -> None:
        if not start:
            return
        try:
            phase()
        except Exception as exc:
            self._record_step(
                phase_name,
                "failed",
                message=f"Phase '{phase_name}' failed: {exc}",
                details={"type": type(exc).__name__},
            )
            raise

    def _resolve_resume_start(self, resume: bool) -> str:
        if not resume:
            return "precheck"
        failed = self.state.last_failed_step_name(exclude_install=True)
        if failed is None:
            return "precheck"
        return failed

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
                        self._run(self._split_command(step), target)
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

    @staticmethod
    def _installer_repo_root() -> Path:
        return Path(__file__).resolve().parents[2]

    @contextmanager
    def _workflow_pythonpath(self) -> Any:
        # Workflow commands run from the target workspace. Prepending the
        # installer repo root keeps explicit `python -m busy_installer...`
        # commands runnable from a local clone without requiring a prior
        # editable install on the host.
        current = os.environ.get("PYTHONPATH")
        entries = [str(self._installer_repo_root())]
        if current:
            entries.extend(item for item in current.split(os.pathsep) if item)
        normalized: list[str] = []
        seen: set[str] = set()
        for item in entries:
            if item in seen:
                continue
            seen.add(item)
            normalized.append(item)
        os.environ["PYTHONPATH"] = os.pathsep.join(normalized)
        try:
            yield
        finally:
            if current is None:
                os.environ.pop("PYTHONPATH", None)
            else:
                os.environ["PYTHONPATH"] = current

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

            mount_state = self._ensure_adapter_path(adapter, canonical)
            if mount_state == "copy":
                self._record_step("canonical", "ok", message=f"Accepting adapter copy for {binding.name}", details=details)
                return
            if mount_state == "canonical_target":
                self._record_step("canonical", "ok", message=f"Canonical source active for {binding.name}", details=details)
                return
            if mount_state == "would_mount_symlink":
                self._record_step(
                    "canonical",
                    "ok",
                    message=f"Dry-run: would mount canonical symlink for {binding.name}",
                    details=details,
                )
                return
            if adapter.is_symlink() and adapter.resolve() == canonical:
                self._record_step("canonical", "ok", message=f"Canonical symlink active for {binding.name}", details=details)
                return
            raise InstallFailure(f"canonical path must be mounted as symlink: {adapter} -> {canonical}; copy fallback disabled")
        except Exception as exc:
            if binding.required or self.strict_source:
                raise
            self._record_step("canonical", "warning", message=str(exc), details=details)

    def _ensure_adapter_path(self, adapter: Path, canonical: Path) -> str:
        if adapter == canonical:
            return "canonical_target"
        if adapter.is_symlink() and adapter.resolve() == canonical:
            return "symlink"
        adapter_present = adapter.exists() or adapter.is_symlink()
        if not adapter_present:
            if self.dry_run:
                return "would_mount_symlink"
            try:
                self._create_canonical_symlink(adapter, canonical)
                return "symlink"
            except (OSError, RuntimeError) as exc:
                if not self.fallback_allowed:
                    raise InstallFailure(
                        f"canonical path must be mounted as symlink: {adapter} -> {canonical}; copy fallback disabled"
                    ) from exc
                self._replace_with_adapter_copy(adapter, canonical)
                return "copy"
        if self.fallback_allowed and not adapter.is_symlink():
            if self.dry_run:
                return "copy"
            self._replace_with_adapter_copy(adapter, canonical)
            return "copy"
        if self.dry_run:
            return "would_mount_symlink"
        self._replace_with_canonical_symlink(adapter, canonical)
        return "symlink"

    @staticmethod
    def _remove_adapter_path(adapter: Path) -> None:
        if adapter.is_symlink() or adapter.is_file():
            adapter.unlink()
            return
        if adapter.is_dir():
            shutil.rmtree(adapter)
            return
        adapter.unlink(missing_ok=True)

    def _create_canonical_symlink(self, adapter: Path, canonical: Path) -> None:
        adapter.parent.mkdir(parents=True, exist_ok=True)
        adapter.symlink_to(canonical)

    def _replace_with_canonical_symlink(self, adapter: Path, canonical: Path) -> None:
        # In symlink-first mode, workspace adapter copies are staging artifacts.
        # Replace them explicitly so a successful install means the canonical
        # mount is actually active rather than just warned about.
        self._remove_adapter_path(adapter)
        self._create_canonical_symlink(adapter, canonical)

    def _replace_with_adapter_copy(self, adapter: Path, canonical: Path) -> None:
        # Explicit copy fallback must materialize the canonical repo contents,
        # not just leave a placeholder directory that looks mounted.
        self._remove_adapter_path(adapter)
        adapter.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(canonical, adapter)

    def _resolve_repo_mount(self, mount: str) -> Path:
        return (self.workspace / mount).resolve()

    def _catalog_cache_path(self) -> Path:
        catalog = self.manifest.provider_catalog
        if not catalog.cache_path:
            return self.workspace / "provider-catalog.json"
        return self.workspace / catalog.cache_path

    def _sync_provider_catalog(self) -> None:
        catalog = self.manifest.provider_catalog
        if not catalog.enabled:
            self._record_step("provider_catalog", "skipped", message="Provider catalog disabled in manifest.")
            return

        details = {"url": catalog.url, "cache_path": str(self._catalog_cache_path())}
        if self.dry_run:
            self._record_step(
                "provider_catalog",
                "ok",
                message="Dry-run: catalog fetch skipped",
                details=details,
            )
            return

        if not catalog.url:
            if catalog.required and not self._catalog_cache_path().exists():
                self._record_step(
                    "provider_catalog",
                    "failed",
                    message="Catalog required but no provider catalog URL was provided.",
                    details=details,
                )
                raise InstallFailure("provider catalog URL missing")
            self._record_step("provider_catalog", "warning", message="Catalog URL missing; skipping fetch.", details=details)
            return

        self._record_step("provider_catalog", "start", message="Downloading provider catalog", details=details)
        cache_path = self._catalog_cache_path()
        try:
            payload = self._fetch_provider_catalog(catalog.url, timeout_seconds=catalog.timeout_seconds)
            catalog_errors = self._validate_catalog_payload(payload)
            if catalog_errors:
                details["payload_errors"] = catalog_errors
                if catalog.required and not cache_path.exists():
                    self._record_step(
                        "provider_catalog",
                        "failed",
                        message="Catalog payload failed validation and no cached catalog is available.",
                        details=details,
                    )
                    raise InstallFailure("provider catalog payload invalid")
                if cache_path.exists():
                    self._record_step(
                        "provider_catalog",
                        "warning",
                        message="Catalog payload failed validation; using existing cached catalog.",
                        details=details,
                    )
                else:
                    self._record_step(
                        "provider_catalog",
                        "warning",
                        message="Catalog payload failed validation; skipping catalog update.",
                        details=details,
                    )
                return

            provider_count = 0
            if isinstance(payload, dict):
                providers = payload.get("providers")
                if isinstance(providers, list):
                    provider_count = len(providers)
                elif providers is not None:
                    provider_count = 1
            elif isinstance(payload, list):
                provider_count = len(payload)
            if self.dry_run:
                details["action"] = "dry-run"
                details["provider_count"] = provider_count
                self._record_step("provider_catalog", "ok", message="Dry-run: would persist catalog cache", details=details)
                return

            if not cache_path.parent.exists():
                cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            details["provider_count"] = provider_count
            self._record_step("provider_catalog", "ok", message="Provider catalog synced", details=details)
        except Exception as exc:  # pragma: no cover
            if catalog.required and not cache_path.exists():
                self._record_step(
                    "provider_catalog",
                    "failed",
                    message=f"Failed to fetch provider catalog: {exc}",
                    details=details,
                )
                raise InstallFailure(f"provider catalog unavailable: {exc}") from exc
            self._record_step(
                "provider_catalog",
                "warning",
                message=f"Using cached provider catalog because fetch failed: {exc}",
                details=details,
            )

    @staticmethod
    def _validate_catalog_payload(payload: Any) -> List[str]:
        errors: List[str] = []

        if payload is None:
            return ["provider catalog payload is empty"]

        providers = payload
        if isinstance(payload, dict):
            if not payload:
                return ["provider catalog payload is empty"]
            if "providers" in payload:
                providers = payload.get("providers")
                if "version" in payload and not isinstance(payload.get("version"), (str, int, float)):
                    errors.append("provider catalog version must be a string or number if present")

        if not isinstance(providers, (dict, list, tuple)):
            return ["provider catalog providers must be a list or mapping"]

        if isinstance(providers, dict):
            for provider_name, provider_models in providers.items():
                if not isinstance(provider_name, str) or not provider_name.strip():
                    errors.append("provider map key must be a non-empty string")
                    continue
                if not isinstance(provider_models, (str, dict, list, tuple, set, type(None))):
                    errors.append(f"provider '{provider_name}' model definitions must be model ids, objects, or lists")
            return errors

        for index, entry in enumerate(providers):
            if isinstance(entry, (str, int, float, bool)):
                continue
            if not isinstance(entry, dict):
                errors.append(f"provider entry #{index} must be an object")
                continue
            if not any(
                key in entry
                for key in ("id", "name", "provider", "display_name")
            ):
                errors.append(f"provider entry #{index} missing a provider identity field (id/name/provider/display_name)")
                continue

            provider_label = entry.get("id") or entry.get("name") or str(index)
            models = entry.get("models") if isinstance(entry.get("models"), (list, tuple)) else None
            if models is None:
                models = entry.get("model_ids") if isinstance(entry.get("model_ids"), (list, tuple)) else None
            if models is None:
                models = entry.get("model") if isinstance(entry.get("model"), (list, tuple)) else None
            if models is None:
                continue

            for model_index, model_entry in enumerate(models):
                if isinstance(model_entry, str):
                    continue
                if not isinstance(model_entry, dict):
                    errors.append(
                        f"provider '{provider_label}' model #{model_index} must be an id string or object"
                    )
                    continue
                if not any(
                    key in model_entry for key in ("id", "name", "model")
                ):
                    errors.append(
                        f"provider '{provider_label}' model #{model_index} missing model identity field"
                    )

        return errors

    @staticmethod
    def _fetch_provider_catalog(url: str, *, timeout_seconds: int = 6) -> Any:
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "busy-installer/0.1.0"})
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
        return json.loads(raw.decode("utf-8"))

    def _prepare_models(self) -> None:
        if not self.manifest.models:
            self._record_step("models", "skipped", message="No models configured")
            return
        for model in self.manifest.models:
            raw_target = self.workspace / model.target_path
            target = self._model_target_dir(raw_target)
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
        checksum = self._parse_checksum(artifact.checksum)
        marker = target_dir / f".{normalized.name}.checksum"
        if checksum is None and artifact.checksum:
            raise InstallFailure(
                f"Malformed checksum for '{artifact.source}': {artifact.checksum}; expected sha256:<hex_64>"
            )

        if normalized.exists():
            if checksum is None:
                self._record_step("model", "info", message=f"Model artifact already present: {normalized.name}")
                return
            if marker.exists() and marker.read_text(encoding="utf-8").strip() == artifact.checksum:
                self._record_step("model", "info", message=f"Model artifact already cached: {normalized.name}")
                return
            current = self._compute_sha256(normalized)
            if current == checksum[1]:
                marker.write_text(f"{artifact.checksum}\\n", encoding="utf-8")
                self._record_step("model", "info", message=f"Model artifact already cached: {normalized.name}")
                return
            self._record_step("model", "warning", message=f"Model artifact changed; refreshing cached copy: {normalized.name}")

        self._fetch_artifact_source(artifact.source, normalized)
        if checksum is not None:
            self._assert_checksum(normalized, checksum)
            marker.write_text(f"{artifact.checksum}\\n", encoding="utf-8")

    @staticmethod
    def _split_command(command: str) -> list[str]:
        parts = shlex.split(command)
        # Manifest-owned workflow commands should reuse the interpreter that is
        # already running the installer. This fixes Linux hosts without a bare
        # `python` shim without guessing at any other command token.
        if parts and parts[0] == "python":
            parts[0] = sys.executable
        return parts

    @staticmethod
    def _model_target_dir(raw_target: Path) -> Path:
        # Model target paths are directory roots; treat common artifact file extensions
        # as explicit file targets only when clearly specified.
        known_file_suffixes = {".gguf", ".ggml", ".safetensors", ".safetensor", ".bin", ".pt", ".pth", ".onnx"}
        if raw_target.suffix.lower() in known_file_suffixes:
            return raw_target.parent
        return raw_target

    @staticmethod
    def _parse_checksum(checksum: str | None) -> tuple[str, str] | None:
        if not checksum:
            return None
        parts = checksum.split(":", 1)
        if len(parts) != 2:
            return None
        algorithm = parts[0].strip().lower()
        value = parts[1].strip()
        if not value:
            return None
        if not all(char in string.hexdigits for char in value):
            return None
        if value == "0" * len(value):
            return None
        if algorithm in {"sha256", "sha-256"} and len(value) == 64:
            return ("sha256", value.lower())
        return None

    @staticmethod
    def _compute_sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1 << 20):
                h.update(chunk)
        return h.hexdigest()

    def _assert_checksum(self, path: Path, checksum: tuple[str, str]) -> None:
        algorithm, expected = checksum
        if algorithm != "sha256":
            raise InstallFailure(f"unsupported checksum algorithm: {algorithm}")
        actual = self._compute_sha256(path)
        if actual != expected:
            raise InstallFailure(f"checksum mismatch for {path.name}: expected {expected}, got {actual}")

    @staticmethod
    def _is_remote_artifact(source: str) -> bool:
        parsed = urllib.parse.urlparse(source)
        return parsed.scheme in {"http", "https"}

    def _fetch_artifact_source(self, source: str, target: Path) -> None:
        if self._is_remote_artifact(source):
            self._download_remote_artifact(source, target)
            return
        source_path = Path(source).expanduser()
        if not source_path.is_absolute():
            source_path = (self.manifest.path.parent / source_path).resolve()
        if not source_path.exists():
            raise InstallFailure(f"model artifact source missing: {source_path}")
        if source_path.resolve() == target.resolve():
            raise InstallFailure(f"model artifact source equals destination: {source_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)

    @staticmethod
    def _download_remote_artifact(source: str, target: Path) -> None:
        request = urllib.request.Request(
            source,
            headers={
                "Accept": "application/octet-stream",
                "User-Agent": "busy-installer/0.1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            status = getattr(response, "status", 200)
            if status and status != 200:
                raise InstallFailure(f"provider returned HTTP {status} for {source}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as handle:
                shutil.copyfileobj(response, handle)

    def _run_onboarding(self) -> None:
        if not self.manifest.onboarding.command:
            self._record_step("onboarding", "skipped", message="No onboarding workflow configured")
            return
        self._record_step("onboarding", "start", message="Running onboarding")
        if self.dry_run:
            self._record_step("onboarding", "ok", message=f"Would run command: {self.manifest.onboarding.command}")
            return
        with self._workflow_pythonpath():
            self._run(self._split_command(self.manifest.onboarding.command), self.workspace)
        self._record_step("onboarding", "ok", message="Onboarding command completed")

    def _run_smoke(self) -> None:
        if not self.manifest.smoke.command:
            self._record_step("smoke", "skipped", message="No smoke workflow configured")
            return
        self._record_step("smoke", "start", message="Running smoke check")
        if self.dry_run:
            self._record_step("smoke", "ok", message=f"Would run command: {self.manifest.smoke.command}")
            return
        with self._workflow_pythonpath():
            self._run(self._split_command(self.manifest.smoke.command), self.workspace)
        self._record_step("smoke", "ok", message="Smoke check completed")

    def _finalize(self) -> None:
        if self.dry_run:
            self._record_step("finalize", "ok", message="Dry-run complete")
            return
        report = self.workspace / "installer-report.md"
        report.write_text("# Installer report\nInstall completed.\n", encoding="utf-8")
        self._record_step("finalize", "ok", message="Installer finished")

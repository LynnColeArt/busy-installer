from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_manifest_path() -> Path:
    return _repo_root() / "docs" / "installer-manifest.yaml"


def _read_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _read_manifest_wrappers(path: Path) -> tuple[bool, str | None]:
    wrappers_open = False
    management_url = None
    try:
        if not path.exists():
            return wrappers_open, management_url
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError, ValueError):
        return wrappers_open, management_url

    if not isinstance(data, dict):
        return wrappers_open, management_url

    wrappers = data.get("wrappers")
    if not isinstance(wrappers, dict):
        return wrappers_open, management_url

    wrappers_open = bool(wrappers.get("open_management_on_complete", False))
    candidate = wrappers.get("management_url")
    if isinstance(candidate, str) and candidate.strip():
        management_url = candidate.strip()
    return wrappers_open, management_url


@dataclass(frozen=True)
class LauncherConfig:
    command: str
    manifest: Path
    workspace: Path
    skip_models: bool
    strict_source: bool
    allow_copy_fallback: bool
    open_management: bool
    management_url: str | None
    passthrough: tuple[str, ...]


def parse_config(argv: list[str] | None = None) -> LauncherConfig:
    args = list(argv or [])
    if not args or args[0].startswith("-"):
        command = "install"
        passthrough = tuple(args)
    else:
        command = args[0]
        passthrough = tuple(args[1:])

    manifest = Path(os.getenv("BUSY_INSTALL_MANIFEST", str(_default_manifest_path()))).expanduser()
    manifest_open, manifest_url = _read_manifest_wrappers(manifest)
    workspace = Path(os.getenv("BUSY_INSTALL_DIR", "~/pillowfort")).expanduser().resolve()
    skip_models = _read_bool("BUSY_INSTALL_SKIP_MODELS")
    strict_source = _read_bool("BUSY_INSTALL_STRICT_SOURCE")
    allow_copy_fallback = _read_bool("BUSY_INSTALL_ALLOW_COPY_FALLBACK")
    open_management = _read_bool("MANIFEST_UI_OPEN", manifest_open)
    management_url = os.getenv("BUSY_INSTALL_MANAGEMENT_URL", manifest_url or "http://127.0.0.1:8080").strip() or None
    if not management_url:
        management_url = None

    return LauncherConfig(
        command=command,
        manifest=manifest,
        workspace=workspace,
        skip_models=skip_models,
        strict_source=strict_source,
        allow_copy_fallback=allow_copy_fallback,
        open_management=open_management,
        management_url=management_url,
        passthrough=passthrough,
    )


def build_installer_command(config: LauncherConfig) -> list[str]:
    command = [sys.executable, "-m", "busy_installer.cli", config.command, "--manifest", str(config.manifest), "--workspace", str(config.workspace)]

    if config.strict_source:
        command.append("--strict-source")
    if config.allow_copy_fallback:
        command.append("--allow-copy-fallback")
    if config.skip_models:
        command.append("--skip-models")

    if config.passthrough:
        command.extend(config.passthrough)
    return command


def _open_management_url(url: str) -> int:
    open_commands: dict[str, tuple[str, ...]] = {
        "darwin": ("open", url),
        "win32": ("cmd", "/c", "start", "", url),
    }
    if os.name == "nt":
        base_cmd = open_commands["win32"]
    elif sys.platform == "darwin":
        base_cmd = open_commands["darwin"]
    else:
        if shutil.which("xdg-open") is None:
            return 1
        base_cmd = ("xdg-open", url)
    return subprocess.call(base_cmd)


def run(argv: list[str] | None = None) -> int:
    config = parse_config(argv)
    config.workspace.mkdir(parents=True, exist_ok=True)
    log_path = config.workspace / "busy-installer.log"

    installer_command = build_installer_command(config)
    env = os.environ.copy()
    env["PATH"] = os.environ.get("PATH", "")

    log_lines = [
        f"[launcher] running command: {' '.join(shlex.quote(item) for item in installer_command)}",
        f"[launcher] workspace: {config.workspace}",
        f"[launcher] manifest: {config.manifest}",
    ]

    with log_path.open("a", encoding="utf-8") as handle:
        for line in log_lines:
            handle.write(line + "\n")
        result = subprocess.run(
            installer_command,
            cwd=str(_repo_root()),
            stdout=handle,
            stderr=subprocess.STDOUT,
            env=env,
            check=False,
        )
        exit_code = int(result.returncode)

        if exit_code != 0:
            handle.write(f"[launcher] installer failed with exit code: {exit_code}\n")
            handle.write(f"[launcher] rerun with `pillowfort-installer repair` for targeted restart.\n")
            return exit_code

        handle.write("[launcher] installer completed successfully\n")

    if config.open_management and config.management_url and config.command in {"install", "repair"}:
        return _open_management_url(config.management_url)
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())

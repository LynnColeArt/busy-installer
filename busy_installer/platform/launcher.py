from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import json
import argparse
from dataclasses import dataclass
from pathlib import Path

import yaml

_DEFAULT_ONBOARDING_URL = "http://127.0.0.1:8093"
_DEFAULT_MANAGEMENT_URL = "http://127.0.0.1:8031"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_manifest_path() -> Path:
    return _repo_root() / "docs" / "installer-manifest.yaml"


def _read_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _read_manifest_wrappers(path: Path) -> tuple[bool, str | None, str | None]:
    wrappers_open = False
    onboarding_url = None
    management_url = None
    try:
        if not path.exists():
            return wrappers_open, onboarding_url, management_url
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError, ValueError):
        return wrappers_open, onboarding_url, management_url

    if not isinstance(data, dict):
        return wrappers_open, onboarding_url, management_url

    wrappers = data.get("wrappers")
    if not isinstance(wrappers, dict):
        return wrappers_open, onboarding_url, management_url

    wrappers_open = bool(wrappers.get("open_management_on_complete", False))
    candidate = wrappers.get("onboarding_url")
    if isinstance(candidate, str) and candidate.strip():
        onboarding_url = candidate.strip()
    candidate = wrappers.get("management_url")
    if isinstance(candidate, str) and candidate.strip():
        management_url = candidate.strip()
    return wrappers_open, onboarding_url, management_url


def _onboarding_state_path(workspace: Path) -> Path:
    return workspace / ".busy" / "onboarding" / "state.json"


def _load_onboarding_state(workspace: Path) -> str | None:
    path = _onboarding_state_path(workspace)
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    state = payload.get("state")
    if not isinstance(state, str):
        return None
    normalized = state.strip().upper()
    return normalized or None


def _select_completion_surface(config: "LauncherConfig") -> tuple[str, str | None, str | None]:
    onboarding_state = _load_onboarding_state(config.workspace)
    if onboarding_state == "ACTIVE":
        return "management", config.management_url, onboarding_state
    return "onboarding", config.onboarding_url, onboarding_state


@dataclass(frozen=True)
class LauncherConfig:
    command: str
    manifest: Path
    workspace: Path
    skip_models: bool
    strict_source: bool
    allow_copy_fallback: bool
    open_management: bool
    onboarding_url: str | None
    management_url: str | None
    passthrough: tuple[str, ...]


def _parse_launcher_passthrough(args: list[str]) -> tuple[argparse.Namespace, tuple[str, ...]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--manifest")
    parser.add_argument("--workspace")
    parser.add_argument("--skip-models", action="store_true", default=False)
    parser.add_argument("--strict-source", action="store_true", default=False)
    parser.add_argument("--allow-copy-fallback", action="store_true", default=False)
    return parser.parse_known_args(args)


def parse_config(argv: list[str] | None = None) -> LauncherConfig:
    args = list(argv or [])
    if not args or args[0].startswith("-"):
        command = "install"
        raw_passthrough = args
    else:
        command = args[0]
        raw_passthrough = args[1:]

    known_args, passthrough = _parse_launcher_passthrough(raw_passthrough)

    manifest_value = known_args.manifest or os.getenv(
        "BUSY_INSTALL_MANIFEST",
        str(_default_manifest_path()),
    )
    manifest = Path(manifest_value).expanduser().resolve()
    manifest_open, manifest_onboarding_url, manifest_management_url = _read_manifest_wrappers(manifest)
    workspace_value = known_args.workspace or os.getenv("BUSY_INSTALL_DIR", "~/pillowfort")
    workspace = Path(workspace_value).expanduser().resolve()
    skip_models = known_args.skip_models or _read_bool("BUSY_INSTALL_SKIP_MODELS")
    strict_source = known_args.strict_source or _read_bool("BUSY_INSTALL_STRICT_SOURCE")
    allow_copy_fallback = known_args.allow_copy_fallback or _read_bool("BUSY_INSTALL_ALLOW_COPY_FALLBACK")
    open_management = _read_bool("MANIFEST_UI_OPEN", manifest_open)
    onboarding_url = os.getenv(
        "BUSY_INSTALL_ONBOARDING_URL",
        manifest_onboarding_url or _DEFAULT_ONBOARDING_URL,
    ).strip() or None
    management_url = os.getenv(
        "BUSY_INSTALL_MANAGEMENT_URL",
        manifest_management_url or _DEFAULT_MANAGEMENT_URL,
    ).strip() or None
    if not onboarding_url:
        onboarding_url = None
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
        onboarding_url=onboarding_url,
        management_url=management_url,
        passthrough=tuple(passthrough),
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


def _open_url(url: str) -> int:
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

    if config.open_management and config.command in {"install", "repair"}:
        surface_name, target_url, onboarding_state = _select_completion_surface(config)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[launcher] onboarding_state: {onboarding_state or 'missing-or-incomplete'}\n")
            if not target_url:
                handle.write(f"[launcher] no {surface_name} URL configured; skipping browser open.\n")
                return 0
            handle.write(f"[launcher] opening {surface_name} URL: {target_url}\n")
        open_exit = _open_url(target_url)
        with log_path.open("a", encoding="utf-8") as handle:
            if open_exit != 0:
                handle.write(
                    f"[launcher] failed to open {surface_name} URL (rc={open_exit}): {target_url}\n"
                )
            else:
                handle.write(f"[launcher] opened {surface_name} URL successfully\n")
        return 0
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import ipaddress
import os
import shlex
import shutil
import socket
import subprocess
import sys
import json
from urllib.parse import urlparse, urlunparse
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from . import management_bootstrap

_DEFAULT_ONBOARDING_URL = "http://127.0.0.1:8093"
_DEFAULT_MANAGEMENT_URL = "http://127.0.0.1:8031"
_DEFAULT_BUSY_ROOT_LOCAL_PATH = "busy-38-ongoing"
_DEFAULT_MANAGEMENT_ROOT_LOCAL_PATH = "busy-38-ongoing/vendor/busy-38-management-ui"
_VALID_COMMANDS = {"install", "repair", "status", "clean"}
_VALUE_OPTIONS = {"--manifest", "--workspace"}
_BOOLEAN_OPTIONS = {"--skip-models", "--strict-source", "--allow-copy-fallback"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_manifest_path() -> Path:
    return _repo_root() / "busy_installer" / "_bundled" / "installer-manifest.yaml"


def _read_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _read_manifest_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "y"}:
            return True
        if normalized in {"0", "false", "no", "off", "n", ""}:
            return False
    return default


@dataclass(frozen=True)
class ManifestLauncherSettings:
    open_management: bool = False
    onboarding_url: str | None = None
    management_url: str | None = None
    busy_root_local_path: str = _DEFAULT_BUSY_ROOT_LOCAL_PATH
    management_root_local_path: str = _DEFAULT_MANAGEMENT_ROOT_LOCAL_PATH


def _manifest_repo_matches(
    entry: dict[object, object],
    *,
    expected_name: str,
    expected_url_suffix: str,
) -> bool:
    name = str(entry.get("name") or "").strip()
    if name == expected_name:
        return True
    url = str(entry.get("url") or "").strip().lower().rstrip("/")
    return url.endswith(expected_url_suffix)


def _read_manifest_launcher_settings(path: Path) -> ManifestLauncherSettings:
    open_management = False
    onboarding_url = None
    management_url = None
    busy_root_local_path = _DEFAULT_BUSY_ROOT_LOCAL_PATH
    management_root_local_path = _DEFAULT_MANAGEMENT_ROOT_LOCAL_PATH
    try:
        if not path.exists():
            return ManifestLauncherSettings()
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError, ValueError):
        return ManifestLauncherSettings()

    if not isinstance(data, dict):
        return ManifestLauncherSettings()

    wrappers = data.get("wrappers")
    if not isinstance(wrappers, dict):
        wrappers = {}

    open_management = _read_manifest_bool(
        wrappers.get("open_management_on_complete", False),
        default=False,
    )
    candidate = wrappers.get("onboarding_url")
    if isinstance(candidate, str) and candidate.strip():
        onboarding_url = candidate.strip()
    candidate = wrappers.get("management_url")
    if isinstance(candidate, str) and candidate.strip():
        management_url = candidate.strip()
    repositories = data.get("repositories")
    if isinstance(repositories, (list, tuple)):
        for entry in repositories:
            if not isinstance(entry, dict):
                continue
            local_path = str(entry.get("local_path") or "").strip()
            if not local_path:
                continue
            if _manifest_repo_matches(
                entry,
                expected_name="busy38-core",
                expected_url_suffix="busy.git",
            ):
                busy_root_local_path = local_path
                continue
            if _manifest_repo_matches(
                entry,
                expected_name="busy38-management-ui",
                expected_url_suffix="busy38-management-ui.git",
            ):
                management_root_local_path = local_path
    return ManifestLauncherSettings(
        open_management=open_management,
        onboarding_url=onboarding_url,
        management_url=management_url,
        busy_root_local_path=busy_root_local_path,
        management_root_local_path=management_root_local_path,
    )


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
class ManagementLocalBinding:
    bind_host: str
    health_host: str
    port: int


@lru_cache(maxsize=1)
def _local_machine_names() -> frozenset[str]:
    names = {"localhost"}
    for raw_name in (socket.gethostname(), socket.getfqdn()):
        normalized = str(raw_name or "").strip().lower().rstrip(".")
        if normalized:
            names.add(normalized)
    return frozenset(names)


@lru_cache(maxsize=1)
def _local_machine_addresses() -> frozenset[str]:
    addresses = {"127.0.0.1", "::1"}
    for name in _local_machine_names():
        try:
            resolved = socket.getaddrinfo(name, None)
        except OSError:
            continue
        for _family, _socktype, _proto, _canonname, sockaddr in resolved:
            host = str(sockaddr[0] or "").strip()
            if not host:
                continue
            try:
                addresses.add(str(ipaddress.ip_address(host)))
            except ValueError:
                continue
    return frozenset(addresses)


def _management_local_binding(url: str | None) -> ManagementLocalBinding | None:
    if not url:
        return None
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        return None
    default_port = urlparse(_DEFAULT_MANAGEMENT_URL).port or 8031
    try:
        port = parsed.port or default_port
    except ValueError:
        # Invalid management URLs should not crash launcher flow; treat them as
        # non-local and keep browser launch behavior unchanged.
        return None
    if hostname in {"0.0.0.0", "::", "0:0:0:0:0:0:0:0"}:
        return ManagementLocalBinding(bind_host=hostname, health_host="127.0.0.1", port=int(port))
    if hostname in _local_machine_names():
        return ManagementLocalBinding(bind_host=hostname, health_host=hostname, port=int(port))
    try:
        normalized_ip = str(ipaddress.ip_address(hostname))
    except ValueError:
        return None
    if normalized_ip in _local_machine_addresses():
        return ManagementLocalBinding(bind_host=hostname, health_host=hostname, port=int(port))
    return None


def _resolve_workspace_repo_path(workspace: Path, local_path: str) -> Path:
    candidate = Path(local_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (workspace / candidate).resolve()


def _url_netloc_host(host: str) -> str:
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def _browser_management_url(url: str | None) -> str | None:
    if not url:
        return None
    binding = _management_local_binding(url)
    if binding is None:
        return url
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if hostname not in {"0.0.0.0", "::", "0:0:0:0:0:0:0:0"}:
        return url
    port = parsed.port
    netloc = _url_netloc_host(binding.health_host)
    if port is not None:
        netloc = f"{netloc}:{int(port)}"
    return urlunparse(parsed._replace(netloc=netloc))


def _bootstrap_management_surface(config: "LauncherConfig") -> Path | None:
    binding = _management_local_binding(config.management_url)
    if binding is None:
        return None
    busy_root = _resolve_workspace_repo_path(config.workspace, config.busy_root_local_path)
    management_root = _resolve_workspace_repo_path(config.workspace, config.management_root_local_path)
    return management_bootstrap.bootstrap_management(
        workspace=config.workspace,
        busy_root=busy_root,
        management_root=management_root,
        host=binding.bind_host,
        health_host=binding.health_host,
        port=binding.port,
    )


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
    busy_root_local_path: str
    management_root_local_path: str
    passthrough: tuple[str, ...]


@dataclass(frozen=True)
class BrowserOpenResult:
    returncode: int
    action: str


@dataclass(frozen=True)
class _ParsedLauncherArgs:
    command: str | None
    manifest: str | None
    workspace: str | None
    skip_models: bool
    strict_source: bool
    allow_copy_fallback: bool


def _consume_required_option_value(
    args: list[str],
    index: int,
    option_name: str,
) -> tuple[str, int]:
    next_index = index + 1
    if next_index >= len(args):
        raise SystemExit(f"argument {option_name}: expected one argument")

    value = args[next_index]
    if value == "--" or value.startswith("-") or value in _VALUE_OPTIONS or value in _BOOLEAN_OPTIONS:
        raise SystemExit(f"argument {option_name}: expected one argument")

    return value, next_index + 1


def _ensure_option_not_repeated(
    option_name: str,
    current_value: str | None,
) -> None:
    if current_value is not None:
        raise SystemExit(f"argument {option_name}: may only be specified once")


def _ensure_token_not_after_passthrough(
    token: str,
    saw_positional_passthrough: bool,
) -> None:
    if saw_positional_passthrough:
        raise SystemExit(
            f"launcher-owned token may not appear after passthrough tokens: {token}"
        )


def _parse_launcher_passthrough(args: list[str]) -> tuple[_ParsedLauncherArgs, tuple[str, ...]]:
    command: str | None = None
    manifest: str | None = None
    workspace: str | None = None
    skip_models = False
    strict_source = False
    allow_copy_fallback = False
    passthrough: list[str] = []
    saw_positional_passthrough = False

    index = 0
    while index < len(args):
        token = args[index]

        if token == "--":
            passthrough.extend(args[index:])
            break
        if token == "--manifest":
            _ensure_token_not_after_passthrough(token, saw_positional_passthrough)
            _ensure_option_not_repeated(token, manifest)
            manifest, index = _consume_required_option_value(args, index, token)
            continue
        if token == "--workspace":
            _ensure_token_not_after_passthrough(token, saw_positional_passthrough)
            _ensure_option_not_repeated(token, workspace)
            workspace, index = _consume_required_option_value(args, index, token)
            continue
        if token == "--skip-models":
            _ensure_token_not_after_passthrough(token, saw_positional_passthrough)
            skip_models = True
            index += 1
            continue
        if token == "--strict-source":
            _ensure_token_not_after_passthrough(token, saw_positional_passthrough)
            strict_source = True
            index += 1
            continue
        if token == "--allow-copy-fallback":
            _ensure_token_not_after_passthrough(token, saw_positional_passthrough)
            allow_copy_fallback = True
            index += 1
            continue
        if not token.startswith("-") and token in _VALID_COMMANDS and command is None:
            if saw_positional_passthrough:
                raise SystemExit(
                    f"launcher command must appear before passthrough tokens: {token}"
                )
            command = token
            index += 1
            continue
        if not token.startswith("-") and token in _VALID_COMMANDS:
            raise SystemExit(
                f"multiple launcher commands are not allowed: {command} and {token}"
            )

        passthrough.append(token)
        saw_positional_passthrough = True
        index += 1

    return (
        _ParsedLauncherArgs(
            command=command,
            manifest=manifest,
            workspace=workspace,
            skip_models=skip_models,
            strict_source=strict_source,
            allow_copy_fallback=allow_copy_fallback,
        ),
        tuple(passthrough),
    )


def parse_config(argv: list[str] | None = None) -> LauncherConfig:
    args = list(argv or [])
    known_args, passthrough = _parse_launcher_passthrough(args)
    command = known_args.command or "install"

    manifest_value = known_args.manifest or os.getenv(
        "BUSY_INSTALL_MANIFEST",
        str(_default_manifest_path()),
    )
    manifest = Path(manifest_value).expanduser().resolve()
    manifest_settings = _read_manifest_launcher_settings(manifest)
    workspace_value = known_args.workspace or os.getenv("BUSY_INSTALL_DIR", "~/pillowfort")
    workspace = Path(workspace_value).expanduser().resolve()
    skip_models = known_args.skip_models or _read_bool("BUSY_INSTALL_SKIP_MODELS")
    strict_source = known_args.strict_source or _read_bool("BUSY_INSTALL_STRICT_SOURCE")
    allow_copy_fallback = known_args.allow_copy_fallback or _read_bool("BUSY_INSTALL_ALLOW_COPY_FALLBACK")
    open_management = _read_bool("MANIFEST_UI_OPEN", manifest_settings.open_management)
    onboarding_url = os.getenv(
        "BUSY_INSTALL_ONBOARDING_URL",
        manifest_settings.onboarding_url or _DEFAULT_ONBOARDING_URL,
    ).strip() or None
    management_url = os.getenv(
        "BUSY_INSTALL_MANAGEMENT_URL",
        manifest_settings.management_url or _DEFAULT_MANAGEMENT_URL,
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
        busy_root_local_path=manifest_settings.busy_root_local_path,
        management_root_local_path=manifest_settings.management_root_local_path,
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


def _user_message(message: str) -> None:
    print(f"[pillowfort] {message}")


def _recovery_command(config: LauncherConfig) -> str:
    return f"pf --workspace {shlex.quote(str(config.workspace))}"


def _log_summary_line(log_path: Path) -> str | None:
    if not log_path.exists():
        return None
    for raw_line in reversed(log_path.read_text(encoding="utf-8").splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[launcher]"):
            continue
        return line
    return None


def _run_osascript(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )


def _escape_applescript(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _focus_existing_tab_macos(url: str) -> str | None:
    browsers = (
        "Google Chrome",
        "Brave Browser",
        "Microsoft Edge",
        "Arc",
        "Safari",
    )
    escaped_url = _escape_applescript(url)
    for browser in browsers:
        escaped_browser = _escape_applescript(browser)
        if browser == "Safari":
            script = f'''
set targetURL to "{escaped_url}"
set browserName to "{escaped_browser}"
if application browserName is running then
  tell application browserName
    repeat with w in windows
      repeat with t in tabs of w
        if (URL of t as text) starts with targetURL then
          set current tab of w to t
          set index of w to 1
          activate
          return browserName
        end if
      end repeat
    end repeat
  end tell
end if
'''
        else:
            script = f'''
set targetURL to "{escaped_url}"
set browserName to "{escaped_browser}"
if application browserName is running then
  tell application browserName
    repeat with w in windows
      set tabIndex to 0
      repeat with t in tabs of w
        set tabIndex to tabIndex + 1
        if (URL of t as text) starts with targetURL then
          set active tab index of w to tabIndex
          set index of w to 1
          activate
          return browserName
        end if
      end repeat
    end repeat
  end tell
end if
'''
        result = _run_osascript(script)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return None


def _open_url(url: str) -> BrowserOpenResult:
    if sys.platform == "darwin":
        browser = _focus_existing_tab_macos(url)
        if browser:
            return BrowserOpenResult(returncode=0, action=f"focused:{browser}")
        return BrowserOpenResult(returncode=subprocess.call(("open", url)), action="opened")

    open_commands: dict[str, tuple[str, ...]] = {
        "win32": ("cmd", "/c", "start", "", url),
    }
    if os.name == "nt":
        base_cmd = open_commands["win32"]
    else:
        if shutil.which("xdg-open") is None:
            return BrowserOpenResult(returncode=1, action="missing-opener")
        base_cmd = ("xdg-open", url)
    return BrowserOpenResult(returncode=subprocess.call(base_cmd), action="opened")


def run(argv: list[str] | None = None) -> int:
    config = parse_config(argv)
    config.workspace.mkdir(parents=True, exist_ok=True)
    log_path = config.workspace / "busy-installer.log"
    _user_message(f"Workspace: {config.workspace}")
    _user_message(f"Running {config.command} workflow...")

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
            handle.write(f"[launcher] rerun with `{_recovery_command(config)}` for targeted restart.\n")
            handle.flush()
            summary = _log_summary_line(log_path)
            if summary:
                _user_message(summary)
            _user_message(f"Recovery: {_recovery_command(config)}")
            _user_message(f"Log: {log_path}")
            return exit_code

        handle.write("[launcher] installer completed successfully\n")
    _user_message("Setup complete.")

    if config.open_management and config.command in {"install", "repair"}:
        surface_name, target_url, onboarding_state = _select_completion_surface(config)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[launcher] onboarding_state: {onboarding_state or 'missing-or-incomplete'}\n")
            if not target_url:
                handle.write(f"[launcher] no {surface_name} URL configured; skipping browser open.\n")
                _user_message(f"{surface_name.capitalize()} is ready. Browser launch is not configured.")
                return 0
            if surface_name == "management":
                handle.write("[launcher] bootstrapping management surface before browser open\n")
        if surface_name == "management":
            try:
                metadata_path = _bootstrap_management_surface(config)
            except Exception as exc:
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(f"[launcher] management bootstrap failed: {exc}\n")
                _user_message(f"Management UI is not ready: {exc}")
                _user_message(f"Recovery: {_recovery_command(config)}")
                _user_message(f"Log: {log_path}")
                return 1
            if metadata_path is not None:
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(f"[launcher] management runtime ready: {metadata_path}\n")
                _user_message("Management runtime ready.")
            target_url = _browser_management_url(target_url)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[launcher] opening {surface_name} URL: {target_url}\n")
        _user_message(f"Opening {surface_name}: {target_url}")
        open_result = _open_url(target_url)
        with log_path.open("a", encoding="utf-8") as handle:
            if open_result.returncode != 0:
                handle.write(
                    f"[launcher] failed to open {surface_name} URL (rc={open_result.returncode}, action={open_result.action}): {target_url}\n"
                )
                _user_message(f"Open this URL manually: {target_url}")
            else:
                handle.write(
                    f"[launcher] opened {surface_name} URL successfully (action={open_result.action})\n"
                )
                if open_result.action.startswith("focused:"):
                    browser = open_result.action.split(":", 1)[1]
                    _user_message(f"Brought the existing {surface_name} tab to the foreground in {browser}.")
                else:
                    _user_message(f"{surface_name.capitalize()} opened in your browser.")
        return 0
    if config.command in {"install", "repair"}:
        _user_message(f"Reopen with: {_recovery_command(config)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8031
_DEFAULT_TIMEOUT_SECONDS = 20.0


def _workspace_root(raw: str | None) -> Path:
    return Path(raw or ".").expanduser().resolve()


def _busy_root(workspace: Path, raw: str | None) -> Path:
    candidate = Path(raw or "busy-38-ongoing").expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (workspace / candidate).resolve()


def _management_root(busy_root: Path, raw: str | None) -> Path:
    candidate = Path(raw or (busy_root / "vendor" / "busy-38-management-ui")).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (busy_root / candidate).resolve()


def _runtime_dir(workspace: Path) -> Path:
    return workspace / ".busy" / "management"


def _runtime_log_path(workspace: Path) -> Path:
    return _runtime_dir(workspace) / "installer-management.log"


def _runtime_metadata_path(workspace: Path) -> Path:
    return _runtime_dir(workspace) / "installer-management-runtime.json"


def _database_path(workspace: Path) -> Path:
    return _runtime_dir(workspace) / "management.db"


def _http_host_literal(host: str) -> str:
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def _health_url(host: str, port: int) -> str:
    return f"http://{_http_host_literal(host)}:{int(port)}/api/health"


def _read_runtime_metadata(workspace: Path) -> dict[str, Any] | None:
    path = _runtime_metadata_path(workspace)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"installer management runtime metadata is unreadable: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"installer management runtime metadata must be a JSON object: {path}")
    return payload


def _runtime_metadata_pid(metadata: dict[str, Any]) -> int | None:
    raw = metadata.get("pid")
    if isinstance(raw, int) and raw > 0:
        return raw
    return None


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _probe_management_health(host: str, port: int, *, timeout_seconds: float = 1.0) -> tuple[bool, dict[str, Any] | str]:
    url = _health_url(host, port)
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "busy-installer/0.1.0"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return False, f"HTTP {exc.code} from {url}"
    except (URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        return False, str(exc)

    if not isinstance(payload, dict):
        return False, "management health payload is not an object"
    if str(payload.get("status") or "").strip().lower() != "ok":
        return False, str(payload.get("error") or "management health probe returned non-ok status")
    if str(payload.get("service") or "").strip() not in {"", "busy38-management-ui"}:
        return False, f"unexpected management service identity: {payload.get('service')}"
    return True, payload


def _compose_pythonpath(busy_root: Path, current: str | None) -> str:
    entries: list[str] = [str(busy_root)]
    if current:
        entries.extend(item for item in current.split(os.pathsep) if item)
    seen: set[str] = set()
    normalized: list[str] = []
    for item in entries:
        if item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return os.pathsep.join(normalized)


def _build_env(*, workspace: Path, busy_root: Path, host: str, port: int) -> dict[str, str]:
    env = os.environ.copy()
    env["BUSY38_WORKSPACE_ROOT"] = str(workspace)
    env["RW4_WORKSPACE_ROOT"] = str(workspace)
    env["BUSY_RUNTIME_PATH"] = str(busy_root)
    env["MANAGEMENT_DB_PATH"] = str(_database_path(workspace))
    env["PYTHONPATH"] = _compose_pythonpath(busy_root, env.get("PYTHONPATH"))
    env["BUSY38_MANAGEMENT_HOST"] = str(host)
    env["BUSY38_MANAGEMENT_PORT"] = str(int(port))
    return env


def _validate_paths(*, workspace: Path, busy_root: Path, management_root: Path) -> Path:
    if not workspace.exists():
        raise RuntimeError(f"workspace does not exist: {workspace}")
    if not busy_root.exists():
        raise RuntimeError(f"Busy checkout not found: {busy_root}")
    if not management_root.exists():
        raise RuntimeError(f"management UI checkout not found: {management_root}")
    backend_dir = management_root / "backend"
    app_path = backend_dir / "app" / "main.py"
    web_index = management_root / "web" / "index.html"
    if not app_path.exists():
        raise RuntimeError(f"management API app not found: {app_path}")
    if not web_index.exists():
        raise RuntimeError(f"management web app not found: {web_index}")
    return backend_dir


def _write_runtime_metadata(
    *,
    workspace: Path,
    busy_root: Path,
    management_root: Path,
    host: str,
    health_host: str,
    port: int,
    log_path: Path,
    payload: dict[str, Any] | None,
    pid: int | None,
    reused: bool,
) -> Path:
    runtime_dir = _runtime_dir(workspace)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "url": f"http://{_http_host_literal(host)}:{int(port)}/",
        "health_url": _health_url(health_host, port),
        "workspace": str(workspace),
        "busy_root": str(busy_root),
        "management_root": str(management_root),
        "bind_host": str(host),
        "health_host": str(health_host),
        "log_path": str(log_path),
        "database_path": str(_database_path(workspace)),
        "pid": pid,
        "reused_existing_process": bool(reused),
        "recorded_at": int(time.time()),
    }
    if isinstance(payload, dict):
        metadata["status"] = payload.get("status")
        metadata["service"] = payload.get("service")
        metadata["runtime_connected"] = payload.get("runtime_connected")
        metadata["updated_at"] = payload.get("updated_at")
    path = _runtime_metadata_path(workspace)
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _spawn_management_server(
    *,
    workspace: Path,
    busy_root: Path,
    management_root: Path,
    host: str,
    port: int,
) -> subprocess.Popen[Any]:
    backend_dir = _validate_paths(workspace=workspace, busy_root=busy_root, management_root=management_root)
    runtime_dir = _runtime_dir(workspace)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_path = _runtime_log_path(workspace)
    log_handle = log_path.open("ab")

    popen_kwargs: dict[str, Any] = {
        "cwd": str(management_root),
        "env": _build_env(workspace=workspace, busy_root=busy_root, host=host, port=port),
        "stdin": subprocess.DEVNULL,
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
        "close_fds": True,
    }
    if os.name == "nt":
        creationflags = 0
        creationflags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        creationflags |= int(getattr(subprocess, "DETACHED_PROCESS", 0))
        if creationflags:
            popen_kwargs["creationflags"] = creationflags
    else:
        popen_kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--app-dir",
                str(backend_dir),
                "--host",
                str(host),
                "--port",
                str(int(port)),
            ],
            **popen_kwargs,
        )
    finally:
        log_handle.close()
    return proc


def _terminate_process(proc: subprocess.Popen[Any]) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=3.0)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=1.0)
        except Exception:
            pass


def bootstrap_management(
    *,
    workspace: Path,
    busy_root: Path,
    management_root: Path,
    host: str = _DEFAULT_HOST,
    health_host: str | None = None,
    port: int = _DEFAULT_PORT,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    check_only: bool = False,
) -> Path:
    _validate_paths(workspace=workspace, busy_root=busy_root, management_root=management_root)
    effective_health_host = str(health_host or host).strip() or host
    runtime_dir = _runtime_dir(workspace)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_path = _runtime_log_path(workspace)
    if not log_path.exists():
        log_path.touch()

    ok, probe_result = _probe_management_health(effective_health_host, port)
    if ok:
        metadata = _read_runtime_metadata(workspace)
        expected_health_url = _health_url(effective_health_host, port)
        if metadata is None:
            raise RuntimeError(
                f"management surface already reachable at {expected_health_url}, but current workspace has no runtime metadata to prove ownership"
            )
        if (
            metadata.get("workspace") != str(workspace)
            or metadata.get("busy_root") != str(busy_root)
            or metadata.get("management_root") != str(management_root)
            or metadata.get("health_url") != expected_health_url
        ):
            raise RuntimeError(
                f"management surface already reachable at {expected_health_url}, but runtime metadata does not match the current workspace ownership"
            )
        pid = _runtime_metadata_pid(metadata)
        if pid is None or not _pid_is_running(pid):
            raise RuntimeError(
                f"management surface already reachable at {expected_health_url}, but runtime metadata cannot prove the current workspace owns the running process"
            )
        return _write_runtime_metadata(
            workspace=workspace,
            busy_root=busy_root,
            management_root=management_root,
            host=host,
            health_host=effective_health_host,
            port=port,
            log_path=log_path,
            payload=probe_result if isinstance(probe_result, dict) else None,
            pid=pid,
            reused=True,
        )

    if check_only:
        raise RuntimeError(
            f"management surface not reachable at {_health_url(effective_health_host, port)}: {probe_result}"
        )

    proc = _spawn_management_server(
        workspace=workspace,
        busy_root=busy_root,
        management_root=management_root,
        host=host,
        port=port,
    )
    deadline = time.time() + timeout_seconds
    last_error = str(probe_result)
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(
                    f"management process exited before becoming ready (rc={proc.returncode}); see {_runtime_log_path(workspace)}"
                )
            ok, probe_result = _probe_management_health(effective_health_host, port)
            if ok:
                return _write_runtime_metadata(
                    workspace=workspace,
                    busy_root=busy_root,
                    management_root=management_root,
                    host=host,
                    health_host=effective_health_host,
                    port=port,
                    log_path=log_path,
                    payload=probe_result if isinstance(probe_result, dict) else None,
                    pid=proc.pid,
                    reused=False,
                )
            last_error = str(probe_result)
            time.sleep(0.5)
    except Exception:
        _terminate_process(proc)
        raise

    _terminate_process(proc)
    raise RuntimeError(
        f"management surface did not become ready within {timeout_seconds:.1f}s: {last_error}; see {log_path}"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap the management web app for the installer")
    parser.add_argument("--workspace", default=".", help="Workspace root")
    parser.add_argument("--busy-root", default="busy-38-ongoing", help="Relative or absolute Busy checkout root")
    parser.add_argument(
        "--management-root",
        default=None,
        help="Relative or absolute management UI checkout root (defaults to <busy-root>/vendor/busy-38-management-ui)",
    )
    parser.add_argument("--host", default=_DEFAULT_HOST, help="Host to bind")
    parser.add_argument("--port", default=_DEFAULT_PORT, type=int, help="Port to bind")
    parser.add_argument(
        "--timeout-seconds",
        default=_DEFAULT_TIMEOUT_SECONDS,
        type=float,
        help="How long to wait for the management HTTP surface",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only verify that the management HTTP surface is already reachable",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    workspace = _workspace_root(args.workspace)
    busy_root = _busy_root(workspace, args.busy_root)
    management_root = _management_root(busy_root, args.management_root)
    try:
        metadata_path = bootstrap_management(
            workspace=workspace,
            busy_root=busy_root,
            management_root=management_root,
            host=args.host,
            port=args.port,
            timeout_seconds=args.timeout_seconds,
            check_only=args.check_only,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(metadata_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

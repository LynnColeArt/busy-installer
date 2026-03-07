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
_DEFAULT_PORT = 8093
_DEFAULT_TIMEOUT_SECONDS = 20.0


def _workspace_root(raw: str | None) -> Path:
    return Path(raw or ".").expanduser().resolve()


def _busy_root(workspace: Path, raw: str | None) -> Path:
    candidate = Path(raw or "busy-38-ongoing").expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (workspace / candidate).resolve()


def _onboarding_app_dir(busy_root: Path) -> Path:
    return (busy_root / "vendor" / "busy-38-onboarding").resolve()


def _runtime_dir(workspace: Path) -> Path:
    return workspace / ".busy" / "onboarding"


def _runtime_log_path(workspace: Path) -> Path:
    return _runtime_dir(workspace) / "installer-onboarding.log"


def _runtime_metadata_path(workspace: Path) -> Path:
    return _runtime_dir(workspace) / "installer-onboarding-runtime.json"


def _state_url(host: str, port: int) -> str:
    return f"http://{host}:{int(port)}/api/onboarding/state"


def _read_runtime_metadata(workspace: Path) -> dict[str, Any] | None:
    path = _runtime_metadata_path(workspace)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"installer onboarding runtime metadata is unreadable: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"installer onboarding runtime metadata must be a JSON object: {path}")
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


def _probe_onboarding_state(host: str, port: int, *, timeout_seconds: float = 1.0) -> tuple[bool, dict[str, Any] | str]:
    url = _state_url(host, port)
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "busy-installer/0.1.0"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return False, f"HTTP {exc.code} from {url}"
    except (URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        return False, str(exc)

    if not isinstance(payload, dict):
        return False, "onboarding state payload is not an object"
    if payload.get("success") is False:
        return False, str(payload.get("error") or "onboarding state probe returned success=false")
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
    env["BUSY38_ONBOARDING_HOST"] = str(host)
    env["BUSY38_ONBOARDING_PORT"] = str(int(port))
    env["PYTHONPATH"] = _compose_pythonpath(busy_root, env.get("PYTHONPATH"))
    return env


def _validate_paths(*, workspace: Path, busy_root: Path) -> Path:
    if not workspace.exists():
        raise RuntimeError(f"workspace does not exist: {workspace}")
    if not busy_root.exists():
        raise RuntimeError(f"Busy checkout not found: {busy_root}")
    app_dir = _onboarding_app_dir(busy_root)
    app_path = app_dir / "toolkit" / "app.py"
    if not app_path.exists():
        raise RuntimeError(f"onboarding app not found: {app_path}")
    return app_dir


def _write_runtime_metadata(
    *,
    workspace: Path,
    busy_root: Path,
    host: str,
    port: int,
    log_path: Path,
    payload: dict[str, Any] | None,
    pid: int | None,
    reused: bool,
) -> Path:
    runtime_dir = _runtime_dir(workspace)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "url": f"http://{host}:{int(port)}/",
        "state_url": _state_url(host, port),
        "workspace": str(workspace),
        "busy_root": str(busy_root),
        "log_path": str(log_path),
        "pid": pid,
        "reused_existing_process": bool(reused),
        "recorded_at": int(time.time()),
    }
    if isinstance(payload, dict):
        metadata["state"] = payload.get("state")
        metadata["schema_version"] = payload.get("schema_version")
        metadata["context_schema_version"] = payload.get("context_schema_version")
        metadata["import_schema_version"] = payload.get("import_schema_version")
    path = _runtime_metadata_path(workspace)
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _spawn_onboarding_server(*, workspace: Path, busy_root: Path, host: str, port: int) -> subprocess.Popen[Any]:
    app_dir = _validate_paths(workspace=workspace, busy_root=busy_root)
    runtime_dir = _runtime_dir(workspace)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_path = _runtime_log_path(workspace)
    log_handle = log_path.open("ab")

    # Launch the vendored onboarding app as a separate process so the installer
    # phase can return only after the HTTP surface is actually reachable.
    popen_kwargs: dict[str, Any] = {
        "cwd": str(workspace),
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
                "toolkit.app:app",
                "--app-dir",
                str(app_dir),
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


def bootstrap_onboarding(
    *,
    workspace: Path,
    busy_root: Path,
    host: str = _DEFAULT_HOST,
    port: int = _DEFAULT_PORT,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    check_only: bool = False,
) -> Path:
    _validate_paths(workspace=workspace, busy_root=busy_root)
    runtime_dir = _runtime_dir(workspace)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_path = _runtime_log_path(workspace)
    if not log_path.exists():
        log_path.touch()

    ok, probe_result = _probe_onboarding_state(host, port)
    if ok:
        # Fail closed: a live port alone is not enough to prove this workspace
        # owns the onboarding surface that would be reused.
        metadata = _read_runtime_metadata(workspace)
        expected_state_url = _state_url(host, port)
        if metadata is None:
            raise RuntimeError(
                f"onboarding surface already reachable at {expected_state_url}, but current workspace has no runtime metadata to prove ownership"
            )
        if (
            metadata.get("workspace") != str(workspace)
            or metadata.get("busy_root") != str(busy_root)
            or metadata.get("state_url") != expected_state_url
        ):
            raise RuntimeError(
                f"onboarding surface already reachable at {expected_state_url}, but runtime metadata does not match the current workspace ownership"
            )
        existing_pid = _runtime_metadata_pid(metadata)
        if existing_pid is None or not _pid_is_running(existing_pid):
            raise RuntimeError(
                f"onboarding surface already reachable at {expected_state_url}, but runtime metadata cannot prove the current workspace owns the running process"
            )
        return _write_runtime_metadata(
            workspace=workspace,
            busy_root=busy_root,
            host=host,
            port=port,
            log_path=log_path,
            payload=probe_result if isinstance(probe_result, dict) else None,
            pid=existing_pid,
            reused=True,
        )
    if check_only:
        raise RuntimeError(f"onboarding surface not reachable at {_state_url(host, port)}: {probe_result}")

    proc = _spawn_onboarding_server(workspace=workspace, busy_root=busy_root, host=host, port=port)
    deadline = time.monotonic() + max(float(timeout_seconds), 1.0)
    last_error = str(probe_result)
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(
                    f"onboarding process exited before becoming ready (rc={proc.returncode}); see {_runtime_log_path(workspace)}"
                )
            ok, probe_result = _probe_onboarding_state(host, port)
            if ok:
                return _write_runtime_metadata(
                    workspace=workspace,
                    busy_root=busy_root,
                    host=host,
                    port=port,
                    log_path=log_path,
                    payload=probe_result if isinstance(probe_result, dict) else None,
                    pid=proc.pid,
                    reused=False,
                )
            last_error = str(probe_result)
            time.sleep(0.25)
    except Exception:
        _terminate_process(proc)
        raise

    _terminate_process(proc)
    raise RuntimeError(
        f"onboarding surface did not become ready within {timeout_seconds:.1f}s: {last_error}; see {log_path}"
    )


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap the onboarding web app for the installer")
    parser.add_argument("--workspace", default=".", help="Workspace root that contains the Busy checkout")
    parser.add_argument("--busy-root", default="busy-38-ongoing", help="Busy checkout path inside the workspace")
    parser.add_argument("--host", default=_DEFAULT_HOST, help="Onboarding host")
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT, help="Onboarding port")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=_DEFAULT_TIMEOUT_SECONDS,
        help="How long to wait for the onboarding HTTP surface",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only verify that the onboarding HTTP surface is already reachable",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _make_parser().parse_args(argv)
    workspace = _workspace_root(args.workspace)
    busy_root = _busy_root(workspace, args.busy_root)
    try:
        metadata_path = bootstrap_onboarding(
            workspace=workspace,
            busy_root=busy_root,
            host=str(args.host),
            port=int(args.port),
            timeout_seconds=float(args.timeout_seconds),
            check_only=bool(args.check_only),
        )
    except RuntimeError as exc:
        print(f"error: {exc}")
        return 1
    print(f"Onboarding bootstrap ready. state={metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

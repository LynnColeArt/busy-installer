from __future__ import annotations

import json
from pathlib import Path

import pytest

from busy_installer.platform import management_bootstrap


def _create_workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    workspace = tmp_path / "workspace"
    busy_root = workspace / "busy-38-ongoing"
    management_root = busy_root / "vendor" / "busy-38-management-ui"
    app_path = management_root / "backend" / "app" / "main.py"
    web_index = management_root / "web" / "index.html"
    app_path.parent.mkdir(parents=True, exist_ok=True)
    web_index.parent.mkdir(parents=True, exist_ok=True)
    app_path.write_text("app = object()\n", encoding="utf-8")
    web_index.write_text("<!doctype html>\n", encoding="utf-8")
    return workspace, busy_root, management_root


def test_bootstrap_management_reuses_existing_surface(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, busy_root, management_root = _create_workspace(tmp_path)
    log_path = management_bootstrap._runtime_log_path(workspace)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch()
    management_bootstrap._write_runtime_metadata(
        workspace=workspace,
        busy_root=busy_root,
        management_root=management_root,
        host="127.0.0.1",
        port=8031,
        log_path=log_path,
        payload={"status": "ok", "service": "busy38-management-ui", "runtime_connected": True},
        pid=24680,
        reused=False,
    )

    monkeypatch.setattr(
        management_bootstrap,
        "_probe_management_health",
        lambda *_args, **_kwargs: (True, {"status": "ok", "service": "busy38-management-ui", "runtime_connected": True}),
    )
    monkeypatch.setattr(management_bootstrap, "_pid_is_running", lambda pid: pid == 24680)
    monkeypatch.setattr(
        management_bootstrap.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("spawn should not run")),
    )

    metadata_path = management_bootstrap.bootstrap_management(
        workspace=workspace,
        busy_root=busy_root,
        management_root=management_root,
    )

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["reused_existing_process"] is True
    assert payload["pid"] == 24680
    assert payload["service"] == "busy38-management-ui"


def test_bootstrap_management_rejects_foreign_reachable_surface(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, busy_root, management_root = _create_workspace(tmp_path)
    log_path = management_bootstrap._runtime_log_path(workspace)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch()
    management_bootstrap._write_runtime_metadata(
        workspace=workspace,
        busy_root=tmp_path / "other-workspace" / "busy-38-ongoing",
        management_root=tmp_path / "other-workspace" / "busy-38-ongoing" / "vendor" / "busy-38-management-ui",
        host="127.0.0.1",
        port=8031,
        log_path=log_path,
        payload={"status": "ok", "service": "busy38-management-ui", "runtime_connected": False},
        pid=13579,
        reused=False,
    )

    monkeypatch.setattr(
        management_bootstrap,
        "_probe_management_health",
        lambda *_args, **_kwargs: (True, {"status": "ok", "service": "busy38-management-ui", "runtime_connected": False}),
    )
    monkeypatch.setattr(management_bootstrap, "_pid_is_running", lambda pid: pid == 13579)
    monkeypatch.setattr(
        management_bootstrap.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("spawn should not run")),
    )

    with pytest.raises(RuntimeError) as excinfo:
        management_bootstrap.bootstrap_management(
            workspace=workspace,
            busy_root=busy_root,
            management_root=management_root,
        )

    assert "does not match the current workspace ownership" in str(excinfo.value)


def test_bootstrap_management_spawns_server_and_waits_for_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, busy_root, management_root = _create_workspace(tmp_path)
    responses = iter(
        [
            (False, "connection refused"),
            (False, "still starting"),
            (True, {"status": "ok", "service": "busy38-management-ui", "runtime_connected": True}),
        ]
    )
    popen_calls: list[dict[str, object]] = []

    class _FakeProcess:
        pid = 43210
        returncode = None

        def poll(self):
            return None

        def terminate(self):
            self.returncode = -15

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    def fake_popen(command, **kwargs):
        popen_calls.append(
            {
                "command": list(command),
                "cwd": kwargs.get("cwd"),
                "env": dict(kwargs.get("env") or {}),
                "start_new_session": kwargs.get("start_new_session"),
            }
        )
        return _FakeProcess()

    monkeypatch.setattr(management_bootstrap, "_probe_management_health", lambda *_args, **_kwargs: next(responses))
    monkeypatch.setattr(management_bootstrap.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(management_bootstrap.time, "sleep", lambda *_args, **_kwargs: None)

    metadata_path = management_bootstrap.bootstrap_management(
        workspace=workspace,
        busy_root=busy_root,
        management_root=management_root,
    )

    assert len(popen_calls) == 1
    call = popen_calls[0]
    assert call["command"][:4] == [
        management_bootstrap.sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
    ]
    assert call["cwd"] == str(management_root)
    assert str(busy_root) in call["env"]["PYTHONPATH"]
    assert call["env"]["BUSY_RUNTIME_PATH"] == str(busy_root)
    assert call["env"]["MANAGEMENT_DB_PATH"].endswith(".busy/management/management.db")
    assert call["start_new_session"] is True

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["reused_existing_process"] is False
    assert payload["pid"] == 43210
    assert payload["service"] == "busy38-management-ui"
    assert Path(payload["log_path"]).exists()


def test_bootstrap_management_fails_when_spawned_process_exits_early(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, busy_root, management_root = _create_workspace(tmp_path)

    class _FakeProcess:
        pid = 111
        returncode = 9
        terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.terminated = True

    process = _FakeProcess()
    monkeypatch.setattr(management_bootstrap, "_probe_management_health", lambda *_args, **_kwargs: (False, "not ready"))
    monkeypatch.setattr(management_bootstrap.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(management_bootstrap.time, "sleep", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError) as excinfo:
        management_bootstrap.bootstrap_management(
            workspace=workspace,
            busy_root=busy_root,
            management_root=management_root,
        )

    assert "exited before becoming ready" in str(excinfo.value)
    assert process.terminated is True


def test_bootstrap_management_check_only_fails_when_surface_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, busy_root, management_root = _create_workspace(tmp_path)
    monkeypatch.setattr(management_bootstrap, "_probe_management_health", lambda *_args, **_kwargs: (False, "connection refused"))

    with pytest.raises(RuntimeError) as excinfo:
        management_bootstrap.bootstrap_management(
            workspace=workspace,
            busy_root=busy_root,
            management_root=management_root,
            check_only=True,
        )

    assert "not reachable" in str(excinfo.value)

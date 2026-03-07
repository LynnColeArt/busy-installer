from __future__ import annotations

import json
from pathlib import Path

import pytest

from busy_installer.platform import onboarding_bootstrap


def _create_busy_checkout(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    busy_root = workspace / "busy-38-ongoing"
    app_path = busy_root / "vendor" / "busy-38-onboarding" / "toolkit" / "app.py"
    app_path.parent.mkdir(parents=True, exist_ok=True)
    app_path.write_text("app = object()\n", encoding="utf-8")
    return workspace, busy_root


def test_bootstrap_onboarding_reuses_existing_surface(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, busy_root = _create_busy_checkout(tmp_path)

    monkeypatch.setattr(
        onboarding_bootstrap,
        "_probe_onboarding_state",
        lambda *_args, **_kwargs: (
            True,
            {
                "success": True,
                "state": "INTAKE_DRAFTED",
                "schema_version": "onboarding-state-v1",
                "context_schema_version": "onboarding-context-v1",
                "import_schema_version": "onboarding-import-v1",
            },
        ),
    )
    monkeypatch.setattr(onboarding_bootstrap.subprocess, "Popen", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("spawn should not run")))

    metadata_path = onboarding_bootstrap.bootstrap_onboarding(workspace=workspace, busy_root=busy_root)

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["reused_existing_process"] is True
    assert payload["pid"] is None
    assert payload["state"] == "INTAKE_DRAFTED"


def test_bootstrap_onboarding_spawns_server_and_waits_for_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, busy_root = _create_busy_checkout(tmp_path)
    responses = iter(
        [
            (False, "connection refused"),
            (False, "still starting"),
            (
                True,
                {
                    "success": True,
                    "state": "INTAKE_REVIEW_PENDING",
                    "schema_version": "onboarding-state-v1",
                    "context_schema_version": "onboarding-context-v1",
                    "import_schema_version": "onboarding-import-v1",
                },
            ),
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

    monkeypatch.setattr(onboarding_bootstrap, "_probe_onboarding_state", lambda *_args, **_kwargs: next(responses))
    monkeypatch.setattr(onboarding_bootstrap.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(onboarding_bootstrap.time, "sleep", lambda *_args, **_kwargs: None)

    metadata_path = onboarding_bootstrap.bootstrap_onboarding(workspace=workspace, busy_root=busy_root)

    assert len(popen_calls) == 1
    call = popen_calls[0]
    assert call["command"][:4] == [
        onboarding_bootstrap.sys.executable,
        "-m",
        "uvicorn",
        "toolkit.app:app",
    ]
    assert call["cwd"] == str(workspace)
    assert str(busy_root) in call["env"]["PYTHONPATH"]
    assert call["env"]["BUSY38_WORKSPACE_ROOT"] == str(workspace)
    assert call["env"]["BUSY38_ONBOARDING_PORT"] == "8093"
    assert call["start_new_session"] is True

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["reused_existing_process"] is False
    assert payload["pid"] == 43210
    assert payload["state"] == "INTAKE_REVIEW_PENDING"
    assert Path(payload["log_path"]).exists()


def test_bootstrap_onboarding_fails_when_spawned_process_exits_early(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, busy_root = _create_busy_checkout(tmp_path)

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
    monkeypatch.setattr(onboarding_bootstrap, "_probe_onboarding_state", lambda *_args, **_kwargs: (False, "not ready"))
    monkeypatch.setattr(onboarding_bootstrap.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(onboarding_bootstrap.time, "sleep", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError) as excinfo:
        onboarding_bootstrap.bootstrap_onboarding(workspace=workspace, busy_root=busy_root)

    assert "exited before becoming ready" in str(excinfo.value)
    assert process.terminated is True


def test_bootstrap_onboarding_check_only_fails_when_surface_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, busy_root = _create_busy_checkout(tmp_path)
    monkeypatch.setattr(onboarding_bootstrap, "_probe_onboarding_state", lambda *_args, **_kwargs: (False, "connection refused"))

    with pytest.raises(RuntimeError) as excinfo:
        onboarding_bootstrap.bootstrap_onboarding(
            workspace=workspace,
            busy_root=busy_root,
            check_only=True,
        )

    assert "not reachable" in str(excinfo.value)

from __future__ import annotations

from pathlib import Path
import sys

from busy_installer.platform.launcher import build_installer_command, parse_config, run


def _write_manifest(path: Path, wrappers: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""
version: "1.0"
workspace:
  path: "./pillowfort"
repositories: []
source_of_truth:
  entries: []
workflows: {{}}
{wrappers}
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _run_env_manifest(tmp_manifest: Path, monkeypatch) -> None:
    monkeypatch.setenv("BUSY_INSTALL_MANIFEST", str(tmp_manifest))


def test_parse_config_reads_manifest_wrapper_defaults(tmp_path: Path, monkeypatch: object) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    _write_manifest(
        manifest,
        wrappers="""
wrappers:
  open_management_on_complete: true
  management_url: "http://127.0.0.1:8080/admin"
""",
    )
    _run_env_manifest(manifest, monkeypatch)

    config = parse_config([])
    assert config.open_management is True
    assert config.management_url == "http://127.0.0.1:8080/admin"


def test_parse_config_respects_environment_overrides(tmp_path: Path, monkeypatch: object) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    _write_manifest(
        manifest,
        wrappers="""
wrappers:
  open_management_on_complete: true
  management_url: "http://127.0.0.1:8080/admin"
""",
    )
    _run_env_manifest(manifest, monkeypatch)
    monkeypatch.setenv("MANIFEST_UI_OPEN", "0")
    monkeypatch.setenv("BUSY_INSTALL_MANAGEMENT_URL", "http://127.0.0.1:9999/ops")

    config = parse_config([])
    assert config.open_management is False
    assert config.management_url == "http://127.0.0.1:9999/ops"


def test_build_installer_command_includes_passthrough_and_flags(tmp_path: Path, monkeypatch: object) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    _write_manifest(manifest)
    _run_env_manifest(manifest, monkeypatch)
    monkeypatch.setenv("BUSY_INSTALL_SKIP_MODELS", "1")
    monkeypatch.setenv("BUSY_INSTALL_STRICT_SOURCE", "1")

    config = parse_config(["repair", "--skip-models", "alpha"])
    command = build_installer_command(config)

    assert command[0] == sys.executable
    assert config.command == "repair"
    assert "--skip-models" in command
    assert "--strict-source" in command
    assert "alpha" in command


def test_run_executes_installer_and_records_log_and_optional_ui_open(tmp_path: Path, monkeypatch: object) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    _write_manifest(
        manifest,
        wrappers="""
wrappers:
  open_management_on_complete: true
  management_url: "http://127.0.0.1:8080/admin"
""",
    )
    workspace = tmp_path / "pillowfort"
    monkeypatch.setenv("BUSY_INSTALL_MANIFEST", str(manifest))
    monkeypatch.setenv("BUSY_INSTALL_DIR", str(workspace))
    opened: list[str] = []

    class _FakeResult:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    def fake_run(command: list[str], **kwargs) -> _FakeResult:
        # Capture command execution without invoking the real installer.
        opened.append(" ".join(command))
        return _FakeResult(0)

    def fake_open(url: str) -> int:
        opened.append(f"OPEN:{url}")
        return 0

    monkeypatch.setattr("busy_installer.platform.launcher.subprocess.run", fake_run)
    monkeypatch.setattr("busy_installer.platform.launcher._open_management_url", fake_open)

    exit_code = run(["install", "--workspace", str(workspace)])
    assert exit_code == 0
    assert "busy_installer.cli" in opened[0]
    assert any(item == "OPEN:http://127.0.0.1:8080/admin" for item in opened)
    assert (workspace / "busy-installer.log").exists()
    assert "[launcher] running command:" in (workspace / "busy-installer.log").read_text(encoding="utf-8")


def test_run_failure_prevents_management_launch(tmp_path: Path, monkeypatch: object) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    _write_manifest(
        manifest,
        wrappers="""
wrappers:
  open_management_on_complete: true
""",
    )
    workspace = tmp_path / "pillowfort"
    monkeypatch.setenv("BUSY_INSTALL_MANIFEST", str(manifest))
    monkeypatch.setenv("BUSY_INSTALL_DIR", str(workspace))
    opened: list[str] = []

    class _FakeResult:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    monkeypatch.setattr("busy_installer.platform.launcher.subprocess.run", lambda *_args, **_kwargs: _FakeResult(9))
    monkeypatch.setattr("busy_installer.platform.launcher._open_management_url", lambda *_args: opened.append("open-called") or 7)

    exit_code = run(["repair"])
    assert exit_code == 9
    assert opened == []


def test_wrapper_scripts_target_launcher_entrypoint() -> None:
    from pathlib import Path

    base = Path(__file__).resolve().parents[1] / "busy_installer" / "platform"
    linux = (base / "linux" / "launcher.sh").read_text(encoding="utf-8")
    macos = (base / "macos" / "launcher.command").read_text(encoding="utf-8")
    windows = (base / "windows" / "launcher.ps1").read_text(encoding="utf-8")

    assert "busy_installer.platform.launcher" in linux
    assert "busy_installer.platform.launcher" in macos
    assert "busy_installer.platform.launcher" in windows

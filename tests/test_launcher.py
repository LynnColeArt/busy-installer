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
  onboarding_url: "http://127.0.0.1:8093/start"
  management_url: "http://127.0.0.1:8080/admin"
""",
    )
    _run_env_manifest(manifest, monkeypatch)

    config = parse_config([])
    assert config.open_management is True
    assert config.onboarding_url == "http://127.0.0.1:8093/start"
    assert config.management_url == "http://127.0.0.1:8080/admin"


def test_parse_config_respects_environment_overrides(tmp_path: Path, monkeypatch: object) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    _write_manifest(
        manifest,
        wrappers="""
wrappers:
  open_management_on_complete: true
  onboarding_url: "http://127.0.0.1:8093/start"
  management_url: "http://127.0.0.1:8080/admin"
""",
    )
    _run_env_manifest(manifest, monkeypatch)
    monkeypatch.setenv("MANIFEST_UI_OPEN", "0")
    monkeypatch.setenv("BUSY_INSTALL_ONBOARDING_URL", "http://127.0.0.1:7777/onboarding")
    monkeypatch.setenv("BUSY_INSTALL_MANAGEMENT_URL", "http://127.0.0.1:9999/ops")

    config = parse_config([])
    assert config.open_management is False
    assert config.onboarding_url == "http://127.0.0.1:7777/onboarding"
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


def test_parse_config_cli_workspace_overrides_environment(tmp_path: Path, monkeypatch: object) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    cli_workspace = tmp_path / "actual"
    env_workspace = tmp_path / "env"
    _write_manifest(manifest)
    _run_env_manifest(manifest, monkeypatch)
    monkeypatch.setenv("BUSY_INSTALL_DIR", str(env_workspace))

    config = parse_config(["install", "--workspace", str(cli_workspace), "alpha"])

    assert config.workspace == cli_workspace.resolve()
    assert config.passthrough == ("alpha",)


def test_parse_config_cli_manifest_resolves_relative_to_caller(tmp_path: Path, monkeypatch: object) -> None:
    manifest = tmp_path / "manifest.yaml"
    _write_manifest(manifest)
    monkeypatch.chdir(tmp_path)

    config = parse_config(["install", "--manifest", "manifest.yaml"])
    command = build_installer_command(config)

    assert config.manifest == manifest.resolve()
    assert command[command.index("--manifest") + 1] == str(manifest.resolve())


def test_build_installer_command_does_not_duplicate_launcher_owned_flags(tmp_path: Path, monkeypatch: object) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    workspace = tmp_path / "actual"
    _write_manifest(manifest)
    _run_env_manifest(manifest, monkeypatch)

    config = parse_config(
        [
            "repair",
            "--workspace",
            str(workspace),
            "--manifest",
            str(manifest),
            "--skip-models",
            "--strict-source",
            "--allow-copy-fallback",
            "alpha",
        ]
    )
    command = build_installer_command(config)

    assert command.count("--workspace") == 1
    assert command.count("--manifest") == 1
    assert command.count("--skip-models") == 1
    assert command.count("--strict-source") == 1
    assert command.count("--allow-copy-fallback") == 1
    assert command[-1] == "alpha"


def test_run_executes_installer_and_opens_onboarding_when_state_missing(tmp_path: Path, monkeypatch: object) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    _write_manifest(
        manifest,
        wrappers="""
wrappers:
  open_management_on_complete: true
  onboarding_url: "http://127.0.0.1:8093/start"
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
    monkeypatch.setattr("busy_installer.platform.launcher._open_url", fake_open)

    exit_code = run(["install", "--workspace", str(workspace)])
    assert exit_code == 0
    assert "busy_installer.cli" in opened[0]
    assert any(item == "OPEN:http://127.0.0.1:8093/start" for item in opened)
    assert (workspace / "busy-installer.log").exists()
    text = (workspace / "busy-installer.log").read_text(encoding="utf-8")
    assert "[launcher] running command:" in text
    assert "[launcher] opening onboarding URL: http://127.0.0.1:8093/start" in text


def test_run_opens_management_when_onboarding_state_is_active(tmp_path: Path, monkeypatch: object) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    _write_manifest(
        manifest,
        wrappers="""
wrappers:
  open_management_on_complete: true
  onboarding_url: "http://127.0.0.1:8093/start"
  management_url: "http://127.0.0.1:8031/admin"
""",
    )
    workspace = tmp_path / "pillowfort"
    onboarding_state = workspace / ".busy" / "onboarding" / "state.json"
    onboarding_state.parent.mkdir(parents=True, exist_ok=True)
    onboarding_state.write_text('{"state":"ACTIVE"}\n', encoding="utf-8")
    monkeypatch.setenv("BUSY_INSTALL_MANIFEST", str(manifest))
    monkeypatch.setenv("BUSY_INSTALL_DIR", str(workspace))
    opened: list[str] = []

    class _FakeResult:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    monkeypatch.setattr(
        "busy_installer.platform.launcher.subprocess.run",
        lambda *_args, **_kwargs: _FakeResult(0),
    )
    monkeypatch.setattr(
        "busy_installer.platform.launcher._open_url",
        lambda url: opened.append(f"OPEN:{url}") or 0,
    )

    exit_code = run(["repair"])
    assert exit_code == 0
    assert opened == ["OPEN:http://127.0.0.1:8031/admin"]


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
    monkeypatch.setattr("busy_installer.platform.launcher._open_url", lambda *_args: opened.append("open-called") or 7)

    exit_code = run(["repair"])
    assert exit_code == 9
    assert opened == []


def test_open_failure_is_logged_but_non_fatal(tmp_path: Path, monkeypatch: object) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    _write_manifest(
        manifest,
        wrappers="""
wrappers:
  open_management_on_complete: true
  onboarding_url: "http://127.0.0.1:8093/start"
""",
    )
    workspace = tmp_path / "pillowfort"
    monkeypatch.setenv("BUSY_INSTALL_MANIFEST", str(manifest))
    monkeypatch.setenv("BUSY_INSTALL_DIR", str(workspace))

    class _FakeResult:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    monkeypatch.setattr(
        "busy_installer.platform.launcher.subprocess.run",
        lambda *_args, **_kwargs: _FakeResult(0),
    )
    monkeypatch.setattr("busy_installer.platform.launcher._open_url", lambda *_args: 7)

    exit_code = run(["install"])
    assert exit_code == 0
    text = (workspace / "busy-installer.log").read_text(encoding="utf-8")
    assert "failed to open onboarding URL (rc=7)" in text


def test_wrapper_scripts_target_launcher_entrypoint() -> None:
    from pathlib import Path

    base = Path(__file__).resolve().parents[1] / "busy_installer" / "platform"
    linux = (base / "linux" / "launcher.sh").read_text(encoding="utf-8")
    macos = (base / "macos" / "launcher.command").read_text(encoding="utf-8")
    windows = (base / "windows" / "launcher.ps1").read_text(encoding="utf-8")

    assert "busy_installer.platform.launcher" in linux
    assert "busy_installer.platform.launcher" in macos
    assert "busy_installer.platform.launcher" in windows

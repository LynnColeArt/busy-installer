from __future__ import annotations

from pathlib import Path
import sys

import pytest

from busy_installer.platform import launcher
from busy_installer.platform.launcher import BrowserOpenResult, build_installer_command, parse_config, run


def _write_manifest(
    path: Path,
    wrappers: str = "",
    repositories: str = "repositories: []",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""
version: "1.0"
workspace:
  path: "./pillowfort"
{repositories}
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


def test_management_local_binding_accepts_wildcard_local_host() -> None:
    binding = launcher._management_local_binding("http://0.0.0.0:8031/admin")

    assert binding == launcher.ManagementLocalBinding(
        bind_host="0.0.0.0",
        health_host="127.0.0.1",
        port=8031,
    )


def test_management_local_binding_accepts_local_machine_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher, "_local_machine_addresses", lambda: frozenset({"127.0.0.1", "192.168.1.44"}))

    binding = launcher._management_local_binding("http://192.168.1.44:8031/admin")

    assert binding == launcher.ManagementLocalBinding(
        bind_host="192.168.1.44",
        health_host="192.168.1.44",
        port=8031,
    )


def test_management_local_binding_rejects_remote_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher, "_local_machine_names", lambda: frozenset({"localhost", "sam-laptop"}))
    monkeypatch.setattr(launcher, "_local_machine_addresses", lambda: frozenset({"127.0.0.1", "::1"}))

    assert launcher._management_local_binding("http://host.docker.internal:8031/admin") is None


def test_management_local_binding_rejects_invalid_url() -> None:
    assert launcher._management_local_binding("http://127.0.0.1:bad-port/admin") is None


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


def test_parse_config_flag_first_command_is_authoritative(tmp_path: Path, monkeypatch: object) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    workspace = tmp_path / "actual"
    _write_manifest(manifest)
    _run_env_manifest(manifest, monkeypatch)

    config = parse_config(["--workspace", str(workspace), "repair"])
    command = build_installer_command(config)

    assert config.command == "repair"
    assert command[command.index("-m") + 2] == "repair"
    assert "--workspace" in command
    assert command[command.index("--workspace") + 1] == str(workspace.resolve())


def test_parse_config_rejects_abbreviated_launcher_flags(tmp_path: Path, monkeypatch: object) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    workspace = tmp_path / "env-workspace"
    _write_manifest(manifest)
    _run_env_manifest(manifest, monkeypatch)
    monkeypatch.setenv("BUSY_INSTALL_DIR", str(workspace))

    config = parse_config(["repair", "--work", str(tmp_path / "other"), "--man", "other.yaml", "--allow-copy"])
    command = build_installer_command(config)

    assert config.command == "repair"
    assert config.workspace == workspace.resolve()
    assert config.manifest == manifest.resolve()
    assert config.allow_copy_fallback is False
    assert config.passthrough == ("--work", str(tmp_path / "other"), "--man", "other.yaml", "--allow-copy")
    assert "--allow-copy-fallback" not in command
    assert command[-5:] == ["--work", str(tmp_path / "other"), "--man", "other.yaml", "--allow-copy"]


def test_parse_config_honors_double_dash_passthrough_boundary(tmp_path: Path, monkeypatch: object) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    workspace = tmp_path / "env-workspace"
    _write_manifest(manifest)
    _run_env_manifest(manifest, monkeypatch)
    monkeypatch.setenv("BUSY_INSTALL_DIR", str(workspace))

    config = parse_config(["install", "--", "--workspace", str(tmp_path / "other")])
    command = build_installer_command(config)

    assert config.command == "install"
    assert config.workspace == workspace.resolve()
    assert config.passthrough == ("--", "--workspace", str(tmp_path / "other"))
    assert command[-3:] == ["--", "--workspace", str(tmp_path / "other")]


@pytest.mark.parametrize(
    ("argv", "expected_message"),
    [
        (["repair", "--workspace", "--strict-source"], "argument --workspace: expected one argument"),
        (["repair", "--manifest", "--workspace"], "argument --manifest: expected one argument"),
        (
            ["repair", "--workspace", "/tmp/one", "--workspace", "/tmp/two"],
            "argument --workspace: may only be specified once",
        ),
        (
            ["repair", "--manifest", "/tmp/one.yaml", "--manifest", "/tmp/two.yaml"],
            "argument --manifest: may only be specified once",
        ),
    ],
)
def test_parse_config_rejects_flag_like_launcher_values(
    argv: list[str],
    expected_message: str,
) -> None:
    with pytest.raises(SystemExit, match=expected_message):
        parse_config(argv)


@pytest.mark.parametrize(
    ("argv", "expected_message"),
    [
        (
            ["install", "repair"],
            "multiple launcher commands are not allowed: install and repair",
        ),
        (
            ["repair", "clean"],
            "multiple launcher commands are not allowed: repair and clean",
        ),
        (
            ["alpha", "repair"],
            "launcher command must appear before passthrough tokens: repair",
        ),
        (
            ["alpha", "--workspace", "/tmp/ws", "repair"],
            "launcher-owned token may not appear after passthrough tokens: --workspace",
        ),
    ],
)
def test_parse_config_rejects_multiple_launcher_commands(
    argv: list[str],
    expected_message: str,
) -> None:
    with pytest.raises(SystemExit, match=expected_message):
        parse_config(argv)


def test_parse_config_double_dash_passthrough_still_fences_command_tokens(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    _write_manifest(manifest)
    _run_env_manifest(manifest, monkeypatch)

    config = parse_config(["--", "repair"])

    assert config.command == "install"
    assert config.passthrough == ("--", "repair")


@pytest.mark.parametrize(
    ("argv", "expected_message"),
    [
        (
            ["alpha", "--workspace", "/tmp/ws"],
            "launcher-owned token may not appear after passthrough tokens: --workspace",
        ),
        (
            ["alpha", "--manifest", "m.yaml"],
            "launcher-owned token may not appear after passthrough tokens: --manifest",
        ),
        (
            ["alpha", "--skip-models"],
            "launcher-owned token may not appear after passthrough tokens: --skip-models",
        ),
        (
            ["install", "alpha", "--workspace", "/tmp/ws"],
            "launcher-owned token may not appear after passthrough tokens: --workspace",
        ),
        (
            ["install", "alpha", "--allow-copy-fallback"],
            "launcher-owned token may not appear after passthrough tokens: --allow-copy-fallback",
        ),
    ],
)
def test_parse_config_rejects_launcher_owned_tokens_after_positional_passthrough(
    argv: list[str],
    expected_message: str,
) -> None:
    with pytest.raises(SystemExit, match=expected_message):
        parse_config(argv)


def test_parse_config_cli_manifest_resolves_relative_to_caller(tmp_path: Path, monkeypatch: object) -> None:
    manifest = tmp_path / "manifest.yaml"
    _write_manifest(manifest)
    monkeypatch.chdir(tmp_path)

    config = parse_config(["install", "--manifest", "manifest.yaml"])
    command = build_installer_command(config)

    assert config.manifest == manifest.resolve()
    assert command[command.index("--manifest") + 1] == str(manifest.resolve())


def test_parse_config_manifest_wrapper_false_string_fails_closed(tmp_path: Path, monkeypatch: object) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    _write_manifest(
        manifest,
        wrappers="""
wrappers:
  open_management_on_complete: "false"
""",
    )
    _run_env_manifest(manifest, monkeypatch)

    config = parse_config([])

    assert config.open_management is False


def test_parse_config_manifest_wrapper_invalid_boolean_fails_closed(tmp_path: Path, monkeypatch: object) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    _write_manifest(
        manifest,
        wrappers="""
wrappers:
  open_management_on_complete: "not-a-bool"
""",
    )
    _run_env_manifest(manifest, monkeypatch)

    config = parse_config([])

    assert config.open_management is False


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


def test_parse_config_unknown_bare_token_stays_passthrough(tmp_path: Path, monkeypatch: object) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    _write_manifest(manifest)
    _run_env_manifest(manifest, monkeypatch)

    config = parse_config(["alpha"])

    assert config.command == "install"
    assert config.passthrough == ("alpha",)


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

    def fake_open(url: str) -> BrowserOpenResult:
        opened.append(f"OPEN:{url}")
        return BrowserOpenResult(returncode=0, action="opened")

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
    bootstrap_calls: list[tuple[str, str, str, str, int]] = []
    monkeypatch.setattr(
        "busy_installer.platform.launcher.management_bootstrap.bootstrap_management",
        lambda *, workspace, busy_root, management_root, host, health_host, port: bootstrap_calls.append(
            (str(workspace), str(busy_root), str(management_root), host, health_host, port)
        )
        or (workspace / ".busy" / "management" / "installer-management-runtime.json"),
    )
    monkeypatch.setattr(
        "busy_installer.platform.launcher._open_url",
        lambda url: opened.append(f"OPEN:{url}") or BrowserOpenResult(returncode=0, action="opened"),
    )

    exit_code = run(["repair"])
    assert exit_code == 0
    assert bootstrap_calls == [
        (
            str(workspace.resolve()),
            str((workspace / "busy-38-ongoing").resolve()),
            str((workspace / "busy-38-ongoing" / "vendor" / "busy-38-management-ui").resolve()),
            "127.0.0.1",
            "127.0.0.1",
            8031,
        )
    ]
    assert opened == ["OPEN:http://127.0.0.1:8031/admin"]


def test_run_management_bootstrap_honors_manifest_repo_local_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    _write_manifest(
        manifest,
        repositories="""
repositories:
  - name: busy38-core
    url: "https://example.invalid/Busy.git"
    local_path: "runtime/busy-core"
  - name: busy38-management-ui
    url: "https://example.invalid/busy38-management-ui.git"
    local_path: "vendor/installer-management-ui"
""",
        wrappers="""
wrappers:
  open_management_on_complete: true
  management_url: "http://127.0.0.1:8031/admin"
""",
    )
    workspace = tmp_path / "pillowfort"
    onboarding_state = workspace / ".busy" / "onboarding" / "state.json"
    onboarding_state.parent.mkdir(parents=True, exist_ok=True)
    onboarding_state.write_text('{"state":"ACTIVE"}\n', encoding="utf-8")
    monkeypatch.setenv("BUSY_INSTALL_MANIFEST", str(manifest))
    monkeypatch.setenv("BUSY_INSTALL_DIR", str(workspace))

    class _FakeResult:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    monkeypatch.setattr(
        "busy_installer.platform.launcher.subprocess.run",
        lambda *_args, **_kwargs: _FakeResult(0),
    )
    bootstrap_calls: list[tuple[str, str, str, str, str, int]] = []
    monkeypatch.setattr(
        "busy_installer.platform.launcher.management_bootstrap.bootstrap_management",
        lambda *, workspace, busy_root, management_root, host, health_host, port: bootstrap_calls.append(
            (str(workspace), str(busy_root), str(management_root), host, health_host, port)
        )
        or (workspace / ".busy" / "management" / "installer-management-runtime.json"),
    )
    monkeypatch.setattr(
        "busy_installer.platform.launcher._open_url",
        lambda url: BrowserOpenResult(returncode=0, action="opened"),
    )

    exit_code = run(["repair"])

    assert exit_code == 0
    assert bootstrap_calls == [
        (
            str(workspace.resolve()),
            str((workspace / "runtime" / "busy-core").resolve()),
            str((workspace / "vendor" / "installer-management-ui").resolve()),
            "127.0.0.1",
            "127.0.0.1",
            8031,
        )
    ]


def test_run_skips_management_bootstrap_on_invalid_local_management_url(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    _write_manifest(
        manifest,
        wrappers="""
wrappers:
  open_management_on_complete: true
  onboarding_url: "http://127.0.0.1:8093/start"
  management_url: "http://127.0.0.1:bad-port/admin"
""",
    )
    workspace = tmp_path / "pillowfort"
    onboarding_state = workspace / ".busy" / "onboarding" / "state.json"
    onboarding_state.parent.mkdir(parents=True, exist_ok=True)
    onboarding_state.write_text('{"state":"ACTIVE"}\n', encoding="utf-8")
    monkeypatch.setenv("BUSY_INSTALL_MANIFEST", str(manifest))
    monkeypatch.setenv("BUSY_INSTALL_DIR", str(workspace))

    class _FakeResult:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    monkeypatch.setattr(
        "busy_installer.platform.launcher.subprocess.run",
        lambda *_args, **_kwargs: _FakeResult(0),
    )
    bootstrap_calls: list[tuple[str, str, str, str, int]] = []
    monkeypatch.setattr(
        "busy_installer.platform.launcher.management_bootstrap.bootstrap_management",
        lambda **_kwargs: bootstrap_calls.append(("bootstrap should not run") )
        or (_ for _ in ()).throw(AssertionError("management bootstrap should not run")),
    )
    opened: list[str] = []
    monkeypatch.setattr(
        "busy_installer.platform.launcher._open_url",
        lambda *_args: opened.append(f"OPEN:{_args[0]}") or BrowserOpenResult(returncode=0, action="opened"),
    )

    exit_code = run(["repair"])

    assert exit_code == 0
    assert bootstrap_calls == []
    assert opened == ["OPEN:http://127.0.0.1:bad-port/admin"]


def test_run_management_bootstrap_failure_is_actionable_and_prevents_browser_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    _write_manifest(
        manifest,
        wrappers="""
wrappers:
  open_management_on_complete: true
  management_url: "http://127.0.0.1:8031"
""",
    )
    workspace = tmp_path / "pillowfort"
    onboarding_state = workspace / ".busy" / "onboarding" / "state.json"
    onboarding_state.parent.mkdir(parents=True, exist_ok=True)
    onboarding_state.write_text('{"state":"ACTIVE"}\n', encoding="utf-8")
    monkeypatch.setenv("BUSY_INSTALL_MANIFEST", str(manifest))
    monkeypatch.setenv("BUSY_INSTALL_DIR", str(workspace))

    class _FakeResult:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    monkeypatch.setattr(
        "busy_installer.platform.launcher.subprocess.run",
        lambda *_args, **_kwargs: _FakeResult(0),
    )
    monkeypatch.setattr(
        "busy_installer.platform.launcher.management_bootstrap.bootstrap_management",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("management UI checkout not found")),
    )
    monkeypatch.setattr(
        "busy_installer.platform.launcher._open_url",
        lambda *_args: (_ for _ in ()).throw(AssertionError("browser should not open")),
    )

    exit_code = run(["repair"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Management UI is not ready: management UI checkout not found" in output
    assert "Recovery: pf --workspace" in output


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
    monkeypatch.setattr(
        "busy_installer.platform.launcher._open_url",
        lambda *_args: opened.append("open-called") or BrowserOpenResult(returncode=7, action="opened"),
    )

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
    monkeypatch.setattr(
        "busy_installer.platform.launcher._open_url",
        lambda *_args: BrowserOpenResult(returncode=7, action="missing-opener"),
    )

    exit_code = run(["install"])
    assert exit_code == 0
    text = (workspace / "busy-installer.log").read_text(encoding="utf-8")
    assert "failed to open onboarding URL (rc=7, action=missing-opener)" in text


def test_run_prints_high_signal_recovery_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = tmp_path / "docs" / "installer-manifest.yaml"
    _write_manifest(manifest)
    workspace = tmp_path / "pillowfort"
    monkeypatch.setenv("BUSY_INSTALL_MANIFEST", str(manifest))
    monkeypatch.setenv("BUSY_INSTALL_DIR", str(workspace))

    class _FakeResult:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    def fake_run(_command: list[str], **kwargs) -> _FakeResult:
        handle = kwargs["stdout"]
        handle.write("Install failed: boom\n")
        return _FakeResult(4)

    monkeypatch.setattr("busy_installer.platform.launcher.subprocess.run", fake_run)

    exit_code = run(["repair"])

    output = capsys.readouterr().out
    assert exit_code == 4
    assert "[pillowfort] Install failed: boom" in output
    assert "Recovery: pf --workspace" in output
    assert "Log:" in output


def test_run_prints_manual_url_when_browser_open_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
    monkeypatch.setattr(
        "busy_installer.platform.launcher._open_url",
        lambda *_args: BrowserOpenResult(returncode=7, action="missing-opener"),
    )

    exit_code = run(["repair"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Opening onboarding: http://127.0.0.1:8093/start" in output
    assert "Open this URL manually: http://127.0.0.1:8093/start" in output


def test_run_prints_focus_message_when_existing_browser_tab_is_reused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
    monkeypatch.setattr(
        "busy_installer.platform.launcher._open_url",
        lambda *_args: BrowserOpenResult(returncode=0, action="focused:Google Chrome"),
    )

    exit_code = run(["repair"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Brought the existing onboarding tab to the foreground in Google Chrome." in output


def test_platform_wrapper_scripts_target_app_entrypoint() -> None:
    from pathlib import Path

    base = Path(__file__).resolve().parents[1] / "busy_installer" / "platform"
    linux = (base / "linux" / "launcher.sh").read_text(encoding="utf-8")
    macos = (base / "macos" / "launcher.command").read_text(encoding="utf-8")
    windows = (base / "windows" / "launcher.ps1").read_text(encoding="utf-8")

    assert "bootstrap_env.py" in linux
    assert "bootstrap_env.py" in macos
    assert "bootstrap_env.py" in windows
    assert "busy_installer.app" in linux
    assert "busy_installer.app" in macos
    assert "busy_installer.app" in windows
    assert ".venv/bin/python" in linux
    assert ".venv/bin/python" in macos
    assert ".venv\\Scripts\\python.exe" in windows

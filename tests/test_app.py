from __future__ import annotations

from pathlib import Path

from busy_installer import app, cli
from busy_installer.platform import launcher


def test_app_defaults_to_repair_flow(monkeypatch) -> None:
    observed: list[list[str]] = []

    monkeypatch.setattr(app, "launcher_run", lambda argv: observed.append(list(argv)) or 0)

    exit_code = app.main([])

    assert exit_code == 0
    assert observed == [["repair"]]


def test_app_preserves_explicit_command(monkeypatch) -> None:
    observed: list[list[str]] = []

    monkeypatch.setattr(app, "launcher_run", lambda argv: observed.append(list(argv)) or 0)

    exit_code = app.main(["status", "--workspace", "/tmp/demo"])

    assert exit_code == 0
    assert observed == [["status", "--workspace", "/tmp/demo"]]


def test_app_preserves_flag_first_explicit_command(monkeypatch) -> None:
    observed: list[list[str]] = []

    monkeypatch.setattr(app, "launcher_run", lambda argv: observed.append(list(argv)) or 0)

    exit_code = app.main(["--workspace", "/tmp/demo", "repair"])

    assert exit_code == 0
    assert observed == [["--workspace", "/tmp/demo", "repair"]]


def test_root_bootstrap_wrappers_target_app_entrypoint() -> None:
    root = Path(__file__).resolve().parents[1]

    pf = (root / "pf").read_text(encoding="utf-8")
    pillowfort = (root / "pillowfort").read_text(encoding="utf-8")
    busy = (root / "busy").read_text(encoding="utf-8")
    pf_cmd = (root / "pf.cmd").read_text(encoding="utf-8")
    pillowfort_cmd = (root / "pillowfort.cmd").read_text(encoding="utf-8")
    busy_cmd = (root / "busy.cmd").read_text(encoding="utf-8")
    pf_ps1 = (root / "pf.ps1").read_text(encoding="utf-8")
    pillowfort_ps1 = (root / "pillowfort.ps1").read_text(encoding="utf-8")
    busy_ps1 = (root / "busy.ps1").read_text(encoding="utf-8")

    for text in (pf, pillowfort, busy, pf_cmd, pillowfort_cmd, busy_cmd, pf_ps1, pillowfort_ps1, busy_ps1):
        assert "bootstrap_env.py" in text
        assert "busy_installer.app" in text

    for text in (pf, pillowfort, busy):
        assert "VENV_PYTHON=\"" in text
        assert "BOOTSTRAP_PYTHON" in text
        assert "if [[ -x \"${VENV_PYTHON}\" ]]" in text
        assert "\"${BOOTSTRAP_PYTHON}\" \"${BOOTSTRAP}\"" in text
        assert "bootstrap completed but ${VENV_PYTHON} is missing." in text

    for text in (pf_cmd, pillowfort_cmd, busy_cmd):
        assert "set VENV_PYTHON=%ROOT%.venv\\Scripts\\python.exe" in text
        assert "if exist \"%VENV_PYTHON%\"" in text
        assert "where python3 >nul 2>nul" in text
        assert "where python >nul 2>nul" in text
        assert "set PYTHON=python" in text
        assert "\"%PYTHON%\" \"%BOOTSTRAP%\" >nul" in text
        assert "if errorlevel 1 exit /b %errorlevel%" in text
        assert "exit /b %errorlevel%" in text
        assert "bootstrap completed but %VENV_PYTHON% is missing." in text

    for text in (pf_ps1, pillowfort_ps1, busy_ps1):
        assert "if (Test-Path $VenvPython)" in text
        assert "& $python $Bootstrap | Out-Null" in text
        assert "if ($LASTEXITCODE -ne 0)" in text
        assert "exit $LASTEXITCODE" in text
        assert "if (-not (Test-Path $VenvPython))" in text
        assert "bootstrap completed but $VenvPython is missing." in text


def test_default_manifest_paths_resolve_to_packaged_bundle() -> None:
    root = Path(__file__).resolve().parents[1]
    bundled_manifest = root / "busy_installer" / "_bundled" / "installer-manifest.yaml"
    repo_manifest = root / "docs" / "installer-manifest.yaml"
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")

    assert cli._default_manifest() == bundled_manifest
    assert launcher._default_manifest_path() == bundled_manifest
    assert '_bundled/*.yaml' in pyproject
    assert bundled_manifest.read_text(encoding="utf-8") == repo_manifest.read_text(encoding="utf-8")

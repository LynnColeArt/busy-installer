from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace


def _load_bootstrap_env_module():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "bootstrap_env_under_test",
        root / "scripts" / "bootstrap_env.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_bootstrap_inputs(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        """
[project]
name = "busy-installer"
version = "0.0.0"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (root / "requirements-dev.lock").write_text(
        "pip==26.0.1\nsetuptools==67.6.1\n",
        encoding="utf-8",
    )


def _touch_venv_python(root: Path) -> Path:
    if os.name == "nt":
        python = root / ".venv" / "Scripts" / "python.exe"
    else:
        python = root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("", encoding="utf-8")
    return python


def test_bootstrap_env_reuses_matching_existing_environment(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_bootstrap_env_module()
    _write_bootstrap_inputs(tmp_path)
    venv_python = _touch_venv_python(tmp_path)
    module._write_bootstrap_state(
        tmp_path / ".venv",
        inputs_fingerprint=module._bootstrap_inputs_fingerprint(tmp_path),
        dev=True,
    )
    run_calls: list[tuple[list[str], Path]] = []

    monkeypatch.setattr(module, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "_parse_args", lambda: SimpleNamespace(dev=False))
    monkeypatch.setattr(module, "_run", lambda command, cwd: run_calls.append((list(command), cwd)))

    exit_code = module.main()

    assert exit_code == 0
    assert run_calls == []
    assert json.loads(module._state_path(tmp_path / ".venv").read_text(encoding="utf-8"))["dev"] is True
    output = capsys.readouterr().out
    assert f"[bootstrap] using interpreter: {venv_python}" in output
    assert "[bootstrap] reusing existing environment" in output


def test_bootstrap_env_refreshes_when_dev_dependencies_are_requested(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_bootstrap_env_module()
    _write_bootstrap_inputs(tmp_path)
    venv_python = _touch_venv_python(tmp_path)
    module._write_bootstrap_state(
        tmp_path / ".venv",
        inputs_fingerprint=module._bootstrap_inputs_fingerprint(tmp_path),
        dev=False,
    )
    run_calls: list[tuple[list[str], Path]] = []

    monkeypatch.setattr(module, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "_parse_args", lambda: SimpleNamespace(dev=True))
    monkeypatch.setattr(module, "_run", lambda command, cwd: run_calls.append((list(command), cwd)))

    exit_code = module.main()

    assert exit_code == 0
    assert len(run_calls) == 2
    assert run_calls[0][0][:5] == [
        str(venv_python),
        "-m",
        "pip",
        "install",
        "--upgrade",
    ]
    assert run_calls[1][0][-1] == ".[dev]"
    assert run_calls[0][1] == tmp_path
    assert run_calls[1][1] == tmp_path
    state = json.loads(module._state_path(tmp_path / ".venv").read_text(encoding="utf-8"))
    assert state["dev"] is True
    output = capsys.readouterr().out
    assert "[bootstrap] refreshing environment: dev dependencies requested" in output
    assert "[bootstrap] environment ready" in output

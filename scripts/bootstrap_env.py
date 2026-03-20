from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import venv
from pathlib import Path

_PINNED_PIP = "pip==26.0.1"
_PINNED_SETUPTOOLS = "setuptools==67.6.1"
_BOOTSTRAP_STATE_SCHEMA = 1
_BOOTSTRAP_STATE_FILENAME = ".busy-bootstrap-state.json"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _state_path(venv_dir: Path) -> Path:
    return venv_dir / _BOOTSTRAP_STATE_FILENAME


def _bootstrap_inputs_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for relative_path in ("pyproject.toml", "requirements-dev.lock"):
        path = root / relative_path
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _read_bootstrap_state(venv_dir: Path) -> dict[str, object] | None:
    path = _state_path(venv_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _write_bootstrap_state(venv_dir: Path, *, inputs_fingerprint: str, dev: bool) -> None:
    payload = {
        "schema_version": _BOOTSTRAP_STATE_SCHEMA,
        "inputs_fingerprint": inputs_fingerprint,
        "dev": bool(dev),
    }
    _state_path(venv_dir).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _bootstrap_refresh_reason(root: Path, venv_dir: Path, *, dev: bool) -> str | None:
    python = _venv_python(venv_dir)
    if not python.exists():
        return "missing repo-local interpreter"
    state = _read_bootstrap_state(venv_dir)
    if state is None:
        return "bootstrap state is missing or unreadable"
    if state.get("schema_version") != _BOOTSTRAP_STATE_SCHEMA:
        return "bootstrap state schema changed"
    if state.get("inputs_fingerprint") != _bootstrap_inputs_fingerprint(root):
        return "bootstrap inputs changed"
    if dev and state.get("dev") is not True:
        return "dev dependencies requested"
    return None


def _run(command: list[str], cwd: Path) -> None:
    result = subprocess.run(command, cwd=str(cwd), check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap the local Pillowfort repo environment")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Install dev/test dependencies in addition to the runtime package",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    root = _repo_root()
    venv_dir = root / ".venv"
    refresh_reason = _bootstrap_refresh_reason(root, venv_dir, dev=args.dev)
    if refresh_reason == "missing repo-local interpreter":
        print(f"[bootstrap] creating venv: {venv_dir}")
        venv.EnvBuilder(with_pip=True).create(venv_dir)

    python = _venv_python(venv_dir)
    print(f"[bootstrap] using interpreter: {python}")
    if refresh_reason is None:
        print("[bootstrap] reusing existing environment")
        return 0
    if refresh_reason != "missing repo-local interpreter":
        print(f"[bootstrap] refreshing environment: {refresh_reason}")

    _run([str(python), "-m", "pip", "install", "--upgrade", _PINNED_PIP, _PINNED_SETUPTOOLS], root)
    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--constraint",
            str(root / "requirements-dev.lock"),
            "-e",
            ".[dev]" if args.dev else ".",
        ],
        root,
    )
    _write_bootstrap_state(
        venv_dir,
        inputs_fingerprint=_bootstrap_inputs_fingerprint(root),
        dev=args.dev,
    )
    print("[bootstrap] environment ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

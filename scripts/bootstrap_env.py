from __future__ import annotations

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path

_PINNED_PIP = "pip==26.0.1"
_PINNED_SETUPTOOLS = "setuptools==67.6.1"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


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
    if not _venv_python(venv_dir).exists():
        print(f"[bootstrap] creating venv: {venv_dir}")
        venv.EnvBuilder(with_pip=True).create(venv_dir)

    python = _venv_python(venv_dir)
    print(f"[bootstrap] using interpreter: {python}")
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
    print("[bootstrap] environment ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

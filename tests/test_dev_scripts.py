from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_smoke_manifest_script_passes() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/smoke_manifest.py"],
        cwd=str(root),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[smoke] bundled manifest app path passed" in result.stdout


def test_release_smoke_script_prints_matrix() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/release_smoke.py", "--print-matrix"],
        cwd=str(root),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Installer release smoke matrix" in result.stdout
    assert "macOS" in result.stdout
    assert "Linux" in result.stdout
    assert "Windows" in result.stdout

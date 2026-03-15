from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _venv_python(root: Path) -> Path:
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def _run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print(f"[release-smoke] $ {' '.join(command)}")
    result = subprocess.run(command, cwd=str(cwd), env=env, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def _matrix_lines() -> list[str]:
    return [
        "Installer release smoke matrix",
        "",
        "macOS",
        "  1. python3 scripts/bootstrap_env.py --dev",
        "  2. .venv/bin/python -m pytest -q",
        "  3. .venv/bin/python scripts/smoke_manifest.py",
        "  4. .venv/bin/python scripts/release_smoke.py --current-platform --skip-bootstrap",
        "  5. bash -n busy_installer/platform/macos/launcher.command",
        "",
        "Linux",
        "  1. python3 scripts/bootstrap_env.py --dev",
        "  2. .venv/bin/python -m pytest -q",
        "  3. .venv/bin/python scripts/smoke_manifest.py",
        "  4. .venv/bin/python scripts/release_smoke.py --current-platform --skip-bootstrap",
        "  5. bash -n busy_installer/platform/linux/launcher.sh",
        "",
        "Windows",
        "  1. py -3 scripts\\bootstrap_env.py --dev",
        "  2. .venv\\Scripts\\python.exe -m pytest -q",
        "  3. .venv\\Scripts\\python.exe scripts\\smoke_manifest.py",
        "  4. .venv\\Scripts\\python.exe scripts\\release_smoke.py --current-platform --skip-bootstrap",
        "  5. .\\pf.ps1 --workspace $env:TEMP\\pillowfort-release-smoke --dry-run",
        "",
        "Policy",
        "  - CI/workflow automation remains deferred pending Lynn Cole involvement.",
        "  - The repo-owned smoke command validates the current host only; the matrix remains manual across OSes.",
    ]


def _print_matrix() -> None:
    print("\n".join(_matrix_lines()))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the repo-owned installer release smoke path")
    parser.add_argument(
        "--print-matrix",
        action="store_true",
        help="Print the manual per-platform release smoke matrix and exit",
    )
    parser.add_argument(
        "--current-platform",
        action="store_true",
        help="Run the release smoke path that is valid on the current host",
    )
    parser.add_argument(
        "--skip-bootstrap",
        action="store_true",
        help="Do not rerun scripts/bootstrap_env.py before the smoke checks",
    )
    return parser.parse_args()


def _prepare_ephemeral_home(manifest_path: Path, home: Path) -> None:
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    for entry in payload.get("source_of_truth", {}).get("entries", ()):
        raw_path = entry.get("canonical_path")
        if not isinstance(raw_path, str) or not raw_path:
            continue
        canonical = Path(raw_path.replace("~", str(home), 1)).expanduser()
        canonical.mkdir(parents=True, exist_ok=True)


def _current_platform_wrapper_command(root: Path, workspace: Path) -> list[str]:
    if os.name == "nt":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(root / "pf.ps1"), "--workspace", str(workspace), "--dry-run"]
    return [str(root / "pf"), "--workspace", str(workspace), "--dry-run"]


def _run_current_platform(skip_bootstrap: bool) -> None:
    root = _repo_root()
    bootstrap = root / "scripts" / "bootstrap_env.py"
    manifest = root / "docs" / "installer-manifest.yaml"
    if not skip_bootstrap:
        _run([sys.executable, str(bootstrap), "--dev"], root)

    python = _venv_python(root)
    if not python.exists():
        raise SystemExit(f"missing venv interpreter: {python}")

    _run([str(python), "-m", "pytest", "-q"], root)
    _run([str(python), "scripts/smoke_manifest.py"], root)

    if os.name != "nt":
        for script in (
            root / "pf",
            root / "pillowfort",
            root / "busy",
            root / "busy_installer" / "platform" / "linux" / "launcher.sh",
            root / "busy_installer" / "platform" / "macos" / "launcher.command",
        ):
            _run(["bash", "-n", str(script)], root)

    with tempfile.TemporaryDirectory(prefix="busy-installer-release-smoke-") as tmp:
        temp_root = Path(tmp)
        workspace = temp_root / "workspace"
        home = temp_root / "home"
        _prepare_ephemeral_home(manifest, home)
        env = os.environ.copy()
        env["MANIFEST_UI_OPEN"] = "0"
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
        print(f"[release-smoke] current platform: {platform.system()} {platform.machine()}")
        print(f"[release-smoke] wrapper workspace: {workspace}")
        _run(_current_platform_wrapper_command(root, workspace), root, env=env)

    print("[release-smoke] current-platform smoke passed")


def main() -> int:
    args = _parse_args()
    if args.print_matrix:
        _print_matrix()
        return 0
    if args.current_platform:
        _run_current_platform(skip_bootstrap=args.skip_bootstrap)
        return 0
    raise SystemExit("choose one of: --print-matrix or --current-platform")


if __name__ == "__main__":
    raise SystemExit(main())

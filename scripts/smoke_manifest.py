from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import yaml
from busy_installer.app import main as app_main
from busy_installer.cli import _default_manifest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main() -> int:
    root = _repo_root()
    manifest = _default_manifest()

    with tempfile.TemporaryDirectory(prefix="busy-installer-smoke-") as tmp:
        workspace = Path(tmp) / "workspace"
        home = Path(tmp) / "home"
        payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        for entry in payload.get("source_of_truth", {}).get("entries", ()):
            raw_path = entry.get("canonical_path")
            if not isinstance(raw_path, str) or not raw_path:
                continue
            canonical = Path(raw_path.replace("~", str(home), 1)).expanduser()
            canonical.mkdir(parents=True, exist_ok=True)

        overrides = {
            "MANIFEST_UI_OPEN": "0",
            "HOME": str(home),
            "USERPROFILE": str(home),
        }
        previous = {key: os.environ.get(key) for key in overrides}
        os.environ.update(overrides)

        print(f"[smoke] manifest: {manifest}")
        print(f"[smoke] workspace: {workspace}")
        print(f"[smoke] ephemeral home: {home}")
        cwd = Path.cwd()
        try:
            os.chdir(root)
            exit_code = app_main(["--workspace", str(workspace), "--dry-run"])
        finally:
            os.chdir(cwd)
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        if exit_code != 0:
            raise SystemExit(exit_code)

        state_path = workspace / "install-state.json"
        if not state_path.exists():
            raise SystemExit(f"missing install state: {state_path}")

        payload = json.loads(state_path.read_text(encoding="utf-8"))
        steps = payload.get("steps", [])
        statuses = {(step.get("name"), step.get("status")) for step in steps}
        expected = {
            ("precheck", "ok"),
            ("workspace", "ok"),
            ("provider_catalog", "ok"),
            ("repo", "ok"),
            ("canonical", "ok"),
            ("onboarding", "ok"),
            ("smoke", "ok"),
            ("finalize", "ok"),
        }
        missing = sorted(expected - statuses)
        if missing:
            raise SystemExit(f"smoke validation failed; missing step/status pairs: {missing}")

        print("[smoke] bundled manifest app path passed")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

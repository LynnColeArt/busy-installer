from __future__ import annotations

import json
import runpy
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_ui_manifest_declares_installer_debug_contract() -> None:
    root = _repo_root()
    manifest = json.loads((root / "ui" / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["type"] == "plugin-ui"
    assert manifest["version"] == "1"
    assert manifest["required_api"] == ["/api/plugins/{plugin_id}/ui/debug"]
    assert manifest["plugin_identity"] == {
        "id": "busy-installer",
        "aliases": ["busy-installer", "installer"],
    }

    sections = {section["id"]: section for section in manifest["sections"]}
    assert sections["overview"]["kind"] == "docs"
    assert sections["diagnostics"]["kind"] == "form"

    debug_action = sections["diagnostics"]["actions"][0]
    assert debug_action == {
        "id": "debug",
        "label": "Run plugin debug",
        "method": "GET",
        "description": "Execute the plugin-owned debug handler.",
        "entry_point": "actions:handle_debug",
    }


def test_ui_debug_action_reports_repo_assets() -> None:
    root = _repo_root()
    namespace = runpy.run_path(str(root / "ui" / "actions.py"))
    response = namespace["handle_debug"](
        {"probe": "ui"},
        "get",
        {"source_path": str(root), "plugin_id": "busy-installer"},
    )

    assert response["success"] is True
    assert response["message"] == "plugin ui debug handler executed"
    assert response["payload"] == {
        "plugin": "busy-installer",
        "method": "GET",
        "payload": {"probe": "ui"},
        "source_path": str(root),
        "source_exists": True,
        "manifests": {
            "plugin_manifest_exists": True,
            "ui_manifest_exists": True,
        },
        "entrypoint": "actions:handle_debug",
    }

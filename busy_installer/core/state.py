from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class InstallStepState:
    name: str
    status: str
    message: str | None = None
    details: dict[str, Any] | None = None
    at: str = field(default_factory=_now)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "status": self.status, "at": self.at}
        if self.message is not None:
            out["message"] = self.message
        if self.details is not None:
            out["details"] = self.details
        return out


class InstallState:
    def __init__(self, path: Path):
        self.path = path
        self.steps: list[InstallStepState] = []
        self.metadata: dict[str, Any] = {}

    @property
    def file_path(self) -> Path:
        return self.path / "install-state.json"

    def record(self, name: str, status: str, *, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        self.steps.append(InstallStepState(name=name, status=status, message=message, details=details))
        self.save()

    def set_meta(self, **kwargs: Any) -> None:
        self.metadata.update(kwargs)
        self.save()

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "metadata": self.metadata,
            "steps": [entry.as_dict() for entry in self.steps],
        }

    def save(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        with self.file_path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    def fail(self, name: str, exc: BaseException) -> None:
        self.record(name=name, status="failed", message=str(exc), details={"type": type(exc).__name__})

    @classmethod
    def load(cls, path: Path) -> "InstallState":
        state = cls(path)
        if state.file_path.exists():
            payload = json.loads(state.file_path.read_text(encoding="utf-8"))
            state.metadata = payload.get("metadata", {})
            state.steps = [InstallStepState(**item) for item in payload.get("steps", [])]
        return state

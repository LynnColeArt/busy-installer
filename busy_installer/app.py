from __future__ import annotations

import sys
from typing import Sequence

from .platform.launcher import _parse_launcher_passthrough, run as launcher_run

_VALID_COMMANDS = {"install", "repair", "status", "clean"}


def _normalized_args(argv: Sequence[str] | None = None) -> list[str]:
    args = list(sys.argv[1:] if argv is None else argv)
    parsed, _passthrough = _parse_launcher_passthrough(args)
    if parsed.command in _VALID_COMMANDS:
        return args
    # The frictionless user path always routes through the maintenance-first
    # flow. `repair` resumes failed installs when needed and otherwise
    # revalidates/syncs the current workspace like a fresh install pass.
    return ["repair", *args]


def main(argv: Sequence[str] | None = None) -> int:
    return launcher_run(_normalized_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

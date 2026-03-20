from __future__ import annotations

import sys
from pathlib import Path


# Keep the repository root importable when pytest is launched via its console
# script, which may not place the cwd on sys.path in this environment.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

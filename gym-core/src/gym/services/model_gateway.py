"""Optional trusted-host provider bridge, never imported by the R0 research worker."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# ponytail: source-checkout bridge; package JS resources when distributing wheels.
_ENTRY = Path(__file__).resolve().parents[4] / "model-gateway" / "gateway.mjs"


def run(argv: list[str]) -> int:
    node = shutil.which("node")
    if not node:
        print("error: model gateway requires Node.js >=22.19.0", file=sys.stderr)
        return 2
    if not _ENTRY.is_file():
        print("error: model gateway requires the complete source checkout", file=sys.stderr)
        return 2
    env = dict(os.environ, GYM_MODEL_PYTHON=sys.executable)
    try:
        return subprocess.run([node, str(_ENTRY), *argv], env=env, check=False).returncode
    except OSError:
        print("error: could not start the optional model gateway", file=sys.stderr)
        return 2

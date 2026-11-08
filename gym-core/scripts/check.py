"""One entry point for local checks: `uv run python scripts/check.py [lint|test|ui|smoke|all]`."""
import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
STEPS = {
    "lint": [["ruff", "check", "src", "tests"]],
    "test": [[sys.executable, "-m", "pytest", "-q"]],
    "ui": [[sys.executable, "-m", "pytest", "-q", "tests/test_ui.py"]],
    "smoke": [["node", "tests/browser_smoke.cjs"]],
}
STEPS["all"] = STEPS["lint"] + STEPS["test"] + STEPS["smoke"]


def main(argv: list[str]) -> int:
    name = argv[0] if argv else "all"
    if name not in STEPS:
        print(f"usage: check.py [{'|'.join(STEPS)}]", file=sys.stderr)
        return 2
    for command in STEPS[name]:
        print("$", " ".join(command[1:] if command[0] == sys.executable else command), flush=True)
        if subprocess.run(command, cwd=CORE, check=False).returncode:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

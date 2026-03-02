"""Cross-platform start script for AI Fast API plugin."""

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    venv_dir = Path(".venv")
    if sys.platform == "win32":
        python = venv_dir / "Scripts" / "python.exe"
    else:
        python = venv_dir / "bin" / "python"

    if not python.exists():
        print("Missing .venv python. Install this plugin first.", file=sys.stderr)
        sys.exit(1)

    # Use subprocess instead of os.execv for better Windows compatibility
    proc = subprocess.run(
        [str(python), "main.py"],
        env={**os.environ},
    )
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()

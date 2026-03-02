"""Cross-platform start script for G4F Chat plugin."""

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

    host = os.environ.get("HOST", "0.0.0.0")
    port = os.environ.get("PORT", "8080")
    proc = subprocess.run(
        [str(python), "-m", "g4f.cli", "gui", "--host", host, "--port", port],
    )
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()

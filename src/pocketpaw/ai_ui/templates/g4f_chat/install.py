"""Cross-platform install script for G4F Chat plugin."""

import shutil
import subprocess
import sys
import venv
from pathlib import Path


def _has_uv() -> bool:
    return shutil.which("uv") is not None


def main() -> None:
    venv_dir = Path(".venv")
    if not venv_dir.exists():
        if _has_uv():
            print("Creating virtual environment with uv...")
            subprocess.check_call(["uv", "venv", str(venv_dir)])
        else:
            print("Creating virtual environment...")
            venv.create(str(venv_dir), with_pip=True)

    if sys.platform == "win32":
        python = venv_dir / "Scripts" / "python.exe"
    else:
        python = venv_dir / "bin" / "python"

    if _has_uv():
        print("Installing g4f[gui] with uv...")
        subprocess.check_call(
            ["uv", "pip", "install", "--python", str(python), "-U", "g4f[gui]"],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
    else:
        print("Installing g4f[gui] with pip...")
        subprocess.check_call(
            [str(python), "-m", "pip", "install", "-U", "g4f[gui]"],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

    print("g4f GUI dependencies installed.")


if __name__ == "__main__":
    main()

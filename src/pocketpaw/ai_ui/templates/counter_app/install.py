"""Cross-platform install script for Counter App plugin."""

import shutil
import subprocess
import sys
import venv
from pathlib import Path


def _has_uv() -> bool:
    return shutil.which("uv") is not None


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def main() -> None:
    venv_dir = Path(".venv")
    if not venv_dir.exists():
        if _has_uv():
            print("Creating virtual environment with uv...")
            subprocess.check_call(["uv", "venv", str(venv_dir)])
        else:
            print("Creating virtual environment...")
            venv.create(str(venv_dir), with_pip=True)

    python = _venv_python(venv_dir)

    print("Installing dependencies...")
    if _has_uv():
        subprocess.check_call(
            ["uv", "pip", "install", "--python", str(python), "-r", "requirements.txt"],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
    else:
        subprocess.check_call(
            [str(python), "-m", "pip", "install", "--upgrade", "pip"],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        subprocess.check_call(
            [str(python), "-m", "pip", "install", "-r", "requirements.txt"],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
    print("Counter App installed successfully!")


if __name__ == "__main__":
    main()

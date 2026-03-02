"""Cross-platform install script for AI Fast API plugin."""

import json
import shutil
import subprocess
import sys
import venv
from pathlib import Path


def _has_uv() -> bool:
    return shutil.which("uv") is not None


def main() -> None:
    print("Setting up AI Fast API...")

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

    print("Installing dependencies into isolated .venv...")
    if _has_uv():
        subprocess.check_call(
            ["uv", "pip", "install", "--python", str(python), "-r", "requirements.txt"],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
    else:
        subprocess.check_call(
            [str(python), "-m", "pip", "install", "-r", "requirements.txt"],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

    print("Generating OpenAPI spec from FastAPI routes...")
    result = subprocess.run(
        [
            str(python),
            "-c",
            (
                "from app.main import create_app\n"
                "import json\n"
                "app = create_app()\n"
                "spec = app.openapi()\n"
                "with open('openapi.json', 'w') as f:\n"
                "    json.dump(spec, f, indent=2)\n"
                "print(f'  Generated openapi.json ({len(spec.get(\"paths\", {}))} endpoints)')\n"
            ),
        ],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    if result.returncode != 0:
        print("Warning: Could not generate openapi.json (non-fatal)")

    print("AI Fast API installed successfully!")


if __name__ == "__main__":
    main()

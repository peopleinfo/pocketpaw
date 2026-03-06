"""Built-in: FreeCut — free, open-source video editor with FastAPI backend.

FreeCut is a React + FastAPI application.  The full upstream source is bundled
in the ``source/`` subdirectory so the plugin works **offline** and can be
freely customised.  No git clone is needed at install time.

Install flow
------------
1. ``npm install``            — install Node/React dependencies
2. ``npm run build``          — compile React → dist/
3. ``uv sync`` (in backend/) — create isolated Python venv with FastAPI deps

Start flow
----------
``uv run python main.py`` (in backend/) starts uvicorn which serves both the
API (``/api/*``) and the compiled React SPA at every other path — so only
**one** port (8000) is exposed.
"""

from pathlib import Path

from pocketpaw.ai_ui.builtins._base import BuiltinDefinition

# The FreeCut source is bundled here — no external repository dependency.
_SOURCE_DIR = Path(__file__).resolve().parent / "source"

# ── install.py ────────────────────────────────────────────────────────────────
_INSTALL_PY = r'''"""FreeCut install script — Node build + Python venv setup."""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT    = Path(__file__).parent   # plugin root (copy of freecut repo)
BACKEND = ROOT / "backend"


def _run(*args, cwd=None):
    """Run a command, streaming output, and raise on failure."""
    proc = subprocess.run(
        args,
        cwd=str(cwd or ROOT),
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed (exit {proc.returncode}): {' '.join(str(a) for a in args)}"
        )


def _npm():
    """Return the npm executable (handles Windows .cmd shim)."""
    npm = shutil.which("npm.cmd") if sys.platform == "win32" else None
    npm = npm or shutil.which("npm")
    if not npm:
        raise EnvironmentError(
            "npm not found. Install Node.js from https://nodejs.org/ and retry."
        )
    return npm


def main():
    npm = _npm()

    # 1. Install Node dependencies
    print("==> Installing Node.js dependencies (npm install)...")
    _run(npm, "install", "--prefer-offline", cwd=ROOT)
    print("    Node dependencies installed.")

    # 2. Build React frontend → dist/
    print("==> Building React frontend (npm run build)...")
    _run(npm, "run", "build", cwd=ROOT)
    print("    React frontend built.")

    # 3. Install Python dependencies
    uv = shutil.which("uv")
    if uv:
        print("==> Installing Python dependencies (uv sync)...")
        _run(uv, "sync", cwd=BACKEND)
        print("    Python dependencies installed.")
    else:
        print("==> uv not found, falling back to pip...")
        venv_dir = BACKEND / ".venv"
        if not venv_dir.exists():
            import venv as _venv
            print("    Creating virtual environment...")
            _venv.create(str(venv_dir), with_pip=True)
        python = (
            venv_dir / "Scripts" / "python.exe"
            if sys.platform == "win32"
            else venv_dir / "bin" / "python"
        )
        req = BACKEND / "requirements.txt"
        if req.exists():
            _run(str(python), "-m", "pip", "install", "-r", str(req))
        else:
            _run(
                str(python), "-m", "pip", "install",
                "fastapi>=0.115.0", "uvicorn[standard]>=0.32.0",
                "python-multipart>=0.0.12", "psutil>=6.1.0",
                "imageio-ffmpeg>=0.5.1",
            )
        print("    Python dependencies installed.")

    print("\nFreeCut installed successfully!")


if __name__ == "__main__":
    main()
'''

# ── start.py ──────────────────────────────────────────────────────────────────
_START_PY = r'''"""FreeCut start script — launches the FastAPI backend (which also serves React)."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT    = Path(__file__).parent
BACKEND = ROOT / "backend"

PORT = os.environ.get("PORT", "8000")
HOST = os.environ.get("HOST", "0.0.0.0")


def main():
    uv = shutil.which("uv")
    if uv:
        # uv run picks up the pyproject.toml in backend/ automatically
        cmd = [uv, "run", "python", "main.py"]
    else:
        python = (
            BACKEND / ".venv" / "Scripts" / "python.exe"
            if sys.platform == "win32"
            else BACKEND / ".venv" / "bin" / "python"
        )
        if not python.exists():
            print(
                "ERROR: Python venv not found in backend/.venv\n"
                "       Run the install script first.",
                file=sys.stderr,
            )
            sys.exit(1)
        cmd = [str(python), "main.py"]

    env = os.environ.copy()
    env["PORT"] = PORT
    env["HOST"] = HOST
    # backend/main.py resolves dist/ via: BASE_DIR = Path(__file__).parent.parent

    proc = subprocess.run(cmd, cwd=str(BACKEND), env=env)
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
'''

# ── Manifest ──────────────────────────────────────────────────────────────────
_MANIFEST = {
    "name": "FreeCut",
    "description": (
        "Free, open-source video editor — trim, split, and export with GPU acceleration. "
        "React frontend served by a FastAPI backend (FFmpeg-powered, no cloud needed)."
    ),
    "icon": "scissors",
    "version": "0.0.0",
    "install": "python install.py",
    "start": "python start.py",
    "requires": ["python", "node"],
    "port": 8000,
    "web_view": "iframe",
    "web_view_path": "/",
    "env": {
        "HOST": "0.0.0.0",
        "PORT": "8000",
    },
}

# ── Definition ────────────────────────────────────────────────────────────────
DEFINITION: BuiltinDefinition = {
    "id": "freecut",
    "manifest": _MANIFEST,
    # Full source is bundled in source/ — offline, no git clone needed.
    "source_dir": str(_SOURCE_DIR),
    # install.py / start.py are overlaid on top of the copied source at install time.
    "files": {
        "install.py": _INSTALL_PY,
        "start.py": _START_PY,
    },
    "gallery": {
        "id": "freecut",
        "name": "FreeCut Video Editor",
        "description": (
            "Open-source video editor — React + FastAPI. "
            "Trim, cut, apply effects, GPU-accelerated export. "
            "No cloud, no subscription."
        ),
        "icon": "scissors",
        "source": "builtin:freecut",
        "stars": "React + FastAPI",
        "category": "Media / Video",
    },
}

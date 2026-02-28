"""AI UI — Self-contained system requirements checker.

Downloads and manages binaries in ~/.pocketpaw/bin/ — no OS package
managers (brew, apt, winget) or sudo required.  Like Pinokio, PocketPaw
owns its own toolchain.

Managed binaries: Python, Node.js, Git, UV, FFmpeg, Caddy
"""

import asyncio
import io
import logging
import os
import platform
import re
import shutil
import stat
import sys
import tarfile
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

# ─── Local Binary Directory ─────────────────────────────────────────────

BIN_DIR = Path.home() / ".pocketpaw" / "bin"


def _ensure_bin_dir() -> Path:
    """Create ~/.pocketpaw/bin/ if it doesn't exist and return it."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    return BIN_DIR


def _get_os() -> str:
    """Return os key: macos, linux, or windows."""
    s = platform.system().lower()
    if s == "darwin":
        return "macos"
    return s if s in ("linux", "windows") else "linux"


def _get_arch() -> str:
    """Return architecture key: arm64 or amd64."""
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return "amd64"


def _local_binary(name: str) -> str | None:
    """Check if a binary exists in ~/.pocketpaw/bin/."""
    _ensure_bin_dir()
    suffixes = ["", ".exe"] if _get_os() == "windows" else [""]
    for suffix in suffixes:
        candidate = BIN_DIR / f"{name}{suffix}"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _find_binary(name: str) -> str | None:
    """Find a binary: check managed dirs first, then system PATH.

    Search order:
      1. ~/.pocketpaw/bin/   (PocketPaw-managed)
      2. ~/.local/bin/       (standalone installs, e.g. UV from astral.sh)
      3. System PATH         (fallback)
    """
    local = _local_binary(name)
    if local:
        return local

    # Check ~/.local/bin/ (standalone installs like UV)
    local_bin = Path.home() / ".local" / "bin" / name
    if local_bin.is_file() and os.access(local_bin, os.X_OK):
        return str(local_bin)

    return shutil.which(name)


# ─── Version Cleanup ────────────────────────────────────────────────────

def _friendly_version(req_id: str, raw: str) -> str:
    """Clean up raw version strings for non-technical users.

    Examples:
      'Python 3.12.12'                          → '3.12'
      'v25.6.1'                                 → '25.6'
      'git version 2.39.5 (Apple Git-154)'      → '2.39'
      'uv 0.10.4 (079e3fd05 2026-02-17)'        → '0.10'
      'uv 0.10.4 (Homebrew 2026-02-17)'         → '0.10'
      'v2.11.1 h1:C7sQpsFO...'                  → '2.11'
      'ffmpeg version 7.1 ...'                   → '7.1'
      'static-ffmpeg (Python)'                   → 'Bundled'
    """
    if not raw:
        return "Installed"

    # FFmpeg bundled via Python
    if "static-ffmpeg" in raw.lower() or "static_ffmpeg" in raw.lower():
        return "Bundled"

    # Strip common prefixes
    text = raw.strip()
    for prefix in ("Python ", "git version ", "uv ", "node ", "caddy ", "ffmpeg version "):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):]
            break

    # Remove leading 'v'
    if text.startswith("v"):
        text = text[1:]

    # Extract just the version number (X.Y or X.Y.Z)
    match = re.match(r"(\d+\.\d+(?:\.\d+)?)", text)
    if match:
        parts = match.group(1).split(".")
        # Show major.minor only (e.g., 3.12 not 3.12.12)
        return ".".join(parts[:2])

    # Fallback: return first word if it looks reasonable
    first = text.split()[0] if text.split() else text
    if len(first) <= 20:
        return first

    return "Installed"


# ─── Download Helpers ────────────────────────────────────────────────────

async def _download_bytes(url: str) -> bytes:
    """Download a URL and return raw bytes."""
    import ssl
    import urllib.request

    logger.info("Downloading %s", url)

    # Run blocking download in thread pool
    def _fetch():
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={"User-Agent": "PocketPaw/1.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
            return resp.read()

    return await asyncio.get_event_loop().run_in_executor(None, _fetch)


async def _download_and_extract_binary(
    url: str,
    binary_name: str,
    archive_type: str = "tar.gz",
    inner_path: str | None = None,
) -> str:
    """Download an archive, extract the target binary to ~/.pocketpaw/bin/."""
    _ensure_bin_dir()
    data = await _download_bytes(url)
    dest = BIN_DIR / binary_name

    if archive_type == "binary":
        dest.write_bytes(data)
        dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        logger.info("Installed %s -> %s", binary_name, dest)
        return str(dest)

    # Extract from archive
    def _extract():
        if archive_type == "zip":
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for member in zf.namelist():
                    basename = os.path.basename(member)
                    if inner_path and inner_path in member:
                        dest.write_bytes(zf.read(member))
                        return
                    if basename == binary_name or basename == f"{binary_name}.exe":
                        dest.write_bytes(zf.read(member))
                        return
                raise FileNotFoundError(
                    f"{binary_name} not found in zip."
                )
        else:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
                for member in tf.getmembers():
                    basename = os.path.basename(member.name)
                    if inner_path and inner_path in member.name:
                        f = tf.extractfile(member)
                        if f:
                            dest.write_bytes(f.read())
                        return
                    if basename == binary_name or basename == f"{binary_name}.exe":
                        f = tf.extractfile(member)
                        if f:
                            dest.write_bytes(f.read())
                        return
                raise FileNotFoundError(
                    f"{binary_name} not found in tar."
                )

    await asyncio.get_event_loop().run_in_executor(None, _extract)
    dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    logger.info("Installed %s -> %s", binary_name, dest)
    return str(dest)


# ─── Self-contained Installers ───────────────────────────────────────────


async def _run_exec(*cmd: str, timeout: int = 120) -> tuple[int, str, str]:
    """Run a subprocess and return (returncode, stdout_text, stderr_text)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    rc = proc.returncode
    if rc is None:
        rc = 1
    return rc, stdout.decode(errors="replace"), stderr.decode(errors="replace")


def _error_tail(stdout: str, stderr: str, *, lines: int = 6) -> str:
    """Return a concise tail of stderr/stdout for user-facing errors."""
    raw = (stderr or stdout or "").strip()
    if not raw:
        return ""
    chunks = [line.strip() for line in raw.splitlines() if line.strip()]
    if not chunks:
        return ""
    return "\n".join(chunks[-lines:])

def _caddy_url() -> str:
    """Build the Caddy download URL for this platform."""
    os_key = _get_os()
    arch = _get_arch()
    os_map = {"macos": "darwin", "linux": "linux", "windows": "windows"}
    return f"https://caddyserver.com/api/download?os={os_map[os_key]}&arch={arch}"


def _node_url() -> str:
    """Build the Node.js download URL for this platform."""
    os_key = _get_os()
    arch = _get_arch()
    version = "v22.14.0"
    os_map = {"macos": "darwin", "linux": "linux", "windows": "win"}
    arch_map = {"arm64": "arm64", "amd64": "x64"}
    ext = "zip" if os_key == "windows" else "tar.gz"
    return (
        f"https://nodejs.org/dist/{version}/"
        f"node-{version}-{os_map[os_key]}-{arch_map[arch]}.{ext}"
    )


async def _install_caddy() -> str:
    """Download Caddy binary directly from caddyserver.com API."""
    url = _caddy_url()
    _ensure_bin_dir()
    data = await _download_bytes(url)
    binary_name = "caddy.exe" if _get_os() == "windows" else "caddy"
    dest = BIN_DIR / binary_name
    dest.write_bytes(data)
    dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    logger.info("Installed caddy -> %s", dest)
    return str(dest)


async def _install_ffmpeg() -> str:
    """Install FFmpeg via static_ffmpeg Python package."""
    uv = _find_binary("uv")
    if uv:
        rc, out, err = await _run_exec(
            uv,
            "pip",
            "install",
            "--python",
            sys.executable,
            "static-ffmpeg",
            timeout=180,
        )
    else:
        rc, out, err = await _run_exec(
            sys.executable,
            "-m",
            "pip",
            "install",
            "static-ffmpeg",
            timeout=180,
        )
        # Some uv-managed Python envs don't ship pip by default.
        if rc != 0 and "No module named pip" in err:
            ensure_rc, ensure_out, ensure_err = await _run_exec(
                sys.executable,
                "-m",
                "ensurepip",
                "--upgrade",
                timeout=180,
            )
            if ensure_rc != 0:
                detail = _error_tail(ensure_out, ensure_err) or "ensurepip failed"
                raise RuntimeError(f"Could not bootstrap pip for FFmpeg install. {detail}")
            rc, out, err = await _run_exec(
                sys.executable,
                "-m",
                "pip",
                "install",
                "static-ffmpeg",
                timeout=180,
            )

    if rc != 0:
        detail = _error_tail(out, err) or "pip install static-ffmpeg failed"
        raise RuntimeError(f"Could not install static-ffmpeg. {detail}")

    # Trigger download of binaries
    try:
        import importlib

        static_ffmpeg = importlib.import_module("static_ffmpeg")
        ffmpeg_path, _ = static_ffmpeg.run.get_or_fetch_platform_executables_else_raise()
    except Exception as exc:
        raise RuntimeError(f"static-ffmpeg installed but failed to fetch binaries: {exc}") from exc

    logger.info("Installed ffmpeg via static-ffmpeg -> %s", ffmpeg_path)
    return ffmpeg_path


async def _install_uv() -> str:
    """Install UV via its official install script."""
    os_key = _get_os()
    if os_key == "windows":
        cmd = 'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
    else:
        cmd = "curl -LsSf https://astral.sh/uv/install.sh | sh"

    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    if proc.returncode != 0:
        raise RuntimeError("Could not install UV. Please check your internet connection.")
    return shutil.which("uv") or "uv"


async def _install_node() -> str:
    """Download Node.js binary directly."""
    url = _node_url()
    os_key = _get_os()
    archive_type = "zip" if os_key == "windows" else "tar.gz"
    binary_name = "node.exe" if os_key == "windows" else "node"
    return await _download_and_extract_binary(
        url, binary_name, archive_type, inner_path="bin/node"
    )


async def _install_git() -> str:
    """Install Git — on macOS triggers Xcode CLI tools."""
    os_key = _get_os()
    if os_key == "macos":
        cmd = "xcode-select --install"
    elif os_key == "linux":
        cmd = (
            "conda install -y git 2>/dev/null || "
            "apt install -y git 2>/dev/null || "
            "echo 'Please install git manually'"
        )
    else:
        cmd = "winget install Git.Git --accept-source-agreements --accept-package-agreements"

    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    return shutil.which("git") or "git"


# ─── Installer Registry ─────────────────────────────────────────────────

_INSTALLERS = {
    "caddy": _install_caddy,
    "ffmpeg": _install_ffmpeg,
    "uv": _install_uv,
    "node": _install_node,
    "git": _install_git,
}

# ─── Requirement Definitions ────────────────────────────────────────────
# Descriptions are written for non-technical users.

REQUIREMENTS = [
    {
        "id": "python",
        "name": "Python",
        "icon": "file-code-2",
        "description": "Runs AI apps behind the scenes — already included with PocketPaw",
        "check_cmd": "python3",
        "version_cmd": ["python3", "--version"],
        "install_hint": "Already included",
        "category": "runtime",
    },
    {
        "id": "node",
        "name": "Node.js",
        "icon": "hexagon",
        "description": "Needed by some AI apps that use web technology",
        "check_cmd": "node",
        "version_cmd": ["node", "--version"],
        "install_hint": "One-click install",
        "category": "runtime",
    },
    {
        "id": "git",
        "name": "Git",
        "icon": "git-branch",
        "description": "Downloads AI apps from the internet",
        "check_cmd": "git",
        "version_cmd": ["git", "--version"],
        "install_hint": "One-click install",
        "category": "core",
    },
    {
        "id": "uv",
        "name": "UV",
        "icon": "zap",
        "description": "Installs AI app dependencies super fast",
        "check_cmd": "uv",
        "version_cmd": ["uv", "--version"],
        "install_hint": "One-click install",
        "category": "core",
    },
    {
        "id": "ffmpeg",
        "name": "FFmpeg",
        "icon": "film",
        "description": "Lets AI apps work with audio and video files",
        "check_cmd": "ffmpeg",
        "version_cmd": ["ffmpeg", "-version"],
        "install_hint": "One-click install",
        "category": "optional",
    },
    {
        "id": "caddy",
        "name": "Caddy",
        "icon": "shield-check",
        "description": "Lets you securely access your apps from anywhere",
        "check_cmd": "caddy",
        "version_cmd": ["caddy", "version"],
        "install_hint": "One-click install",
        "category": "optional",
    },
]


# ─── Check Logic ─────────────────────────────────────────────────────────

def _check_static_ffmpeg() -> tuple[bool, str | None, str | None]:
    """Check if ffmpeg is available via the static_ffmpeg Python package."""
    try:
        import importlib

        static_ffmpeg = importlib.import_module("static_ffmpeg")
        ffmpeg_path, _ = static_ffmpeg.run.get_or_fetch_platform_executables_else_raise()
        return True, "Bundled", ffmpeg_path
    except Exception:
        return False, None, None


async def check_requirement(req: dict) -> dict:
    """Check if a requirement is installed (local bin first, then PATH)."""
    binary = req["check_cmd"]
    path = _find_binary(binary)
    installed = path is not None
    version = None

    if installed:
        try:
            version_cmd = req["version_cmd"]
            # If binary found in local bin, use full path
            if path and path != shutil.which(binary):
                version_cmd = [path] + list(version_cmd[1:])

            proc = await asyncio.create_subprocess_exec(
                *version_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            raw = (stdout or stderr or b"").decode(errors="replace").strip()
            raw_first_line = raw.split("\n")[0].strip()
            version = _friendly_version(req["id"], raw_first_line)
        except Exception:
            version = "Installed"
    # Fallback: check static_ffmpeg Python package for ffmpeg
    elif req["id"] == "ffmpeg":
        installed, version, path = _check_static_ffmpeg()

    return {
        "id": req["id"],
        "name": req["name"],
        "icon": req["icon"],
        "description": req["description"],
        "category": req["category"],
        "installed": installed,
        "version": version,
        "install_cmd": req.get("install_hint", ""),
        "path": path,
    }


async def check_all_requirements() -> list[dict]:
    """Check all requirements in parallel."""
    tasks = [check_requirement(req) for req in REQUIREMENTS]
    return await asyncio.gather(*tasks)


# ─── Install Logic ───────────────────────────────────────────────────────

async def install_requirement(req_id: str) -> dict:
    """Install a requirement using self-contained installers.

    No brew, no apt, no sudo — downloads binaries directly.
    """
    req = next((r for r in REQUIREMENTS if r["id"] == req_id), None)
    if not req:
        raise ValueError(f"Unknown requirement: {req_id}")

    installer = _INSTALLERS.get(req_id)
    if not installer:
        # Python is already running if we got here
        if req_id == "python":
            return {
                "status": "ok",
                "message": "Python is already included — you're all set!",
                "output": "",
            }
        raise ValueError(
            f"Sorry, {req['name']} can't be installed automatically right now. "
            f"Please visit the PocketPaw docs for help."
        )

    logger.info("Installing requirement '%s' (self-contained)", req_id)

    try:
        await installer()
    except Exception as exc:
        logger.exception("Install failed for %s", req_id)
        detail = str(exc).strip()
        if detail:
            raise RuntimeError(
                f"Something went wrong installing {req['name']}: {detail}"
            ) from exc
        raise RuntimeError(
            f"Something went wrong installing {req['name']}. "
            f"Please check your internet connection and try again."
        ) from exc

    return {
        "status": "ok",
        "message": f"{req['name']} is ready to use!",
        "output": "",
    }

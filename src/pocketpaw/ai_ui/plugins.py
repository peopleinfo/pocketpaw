"""AI UI — Plugin manager (Pinokio-style workspace isolation).

Each plugin is fully self-contained inside its own directory.  Processes
see *only* their plugin folder: HOME, TMPDIR, cache dirs, and PATH all
point inside it.  No host environment variables leak through.

    plugins/
      my-app/
        pocketpaw.json      <- Required manifest
        install.sh           <- Install script (optional)
        start.sh             <- Launch script (optional)
        stop.sh              <- Stop script (optional)
        .venv/               <- Python venv (created by install)
        .tmp/                <- Sandboxed TMPDIR
        .cache/              <- Sandboxed cache
        .pocketpaw.pid       <- PID file (managed)
        .pocketpaw.log       <- Log file (managed)

pocketpaw.json manifest:
{
  "name": "My App",
  "description": "An AI app",
  "icon": "brain",
  "version": "1.0.0",
  "start": "start.sh",
  "install": "install.sh",
  "stop": "stop.sh",
  "port": 7860,
  "env": {},
  "requires": ["python", "git"],
  "web_view": "iframe",
  "web_view_path": "/"
}

web_view: "native" = integrated Copilot-style chat UI; "iframe" = embed plugin URL.
web_view_path: path for iframe (default "/"); e.g. "/chat" for a /chat page.
"""

import asyncio
import io
import json
import logging
import os
import platform
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
import zipfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PID_FILENAME = ".pocketpaw.pid"
_LOG_FILENAME = ".pocketpaw.log"

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
PLUGINS_DIR = _PROJECT_ROOT / "plugins"

_running_processes: dict[str, asyncio.subprocess.Process] = {}
_codex_auth_sessions: dict[str, dict[str, Any]] = {}
_codex_auth_lock = threading.Lock()
_qwen_auth_sessions: dict[str, dict[str, Any]] = {}
_qwen_auth_lock = threading.Lock()
_gemini_auth_sessions: dict[str, dict[str, Any]] = {}
_gemini_auth_lock = threading.Lock()

# Shared uv cache — all plugins hardlink from here so identical
# packages are stored only once on disk (like pnpm for Python).
_SHARED_UV_CACHE = PLUGINS_DIR / ".uv-cache"

# Minimal system paths needed for basic operation (git, bash, etc.)
_SYSTEM_PATHS = (
    "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    if platform.system() != "Windows"
    else r"C:\Windows\System32;C:\Windows"
)


# ─── Workspace sandbox ──────────────────────────────────────────────────


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    try:
        path.chmod(0o755)
    except OSError:
        logger.debug("Failed to chmod executable: %s", path)


def _ensure_python_shims(plugin_dir: Path, venv_dir: Path, local_bin: Path) -> None:
    """Provide stable `python`/`python3` launch shims for sandboxed scripts."""
    local_bin.mkdir(parents=True, exist_ok=True)
    if platform.system() == "Windows":
        venv_py = venv_dir / "Scripts" / "python.exe"
        fallback = Path(sys.executable)
        shim = (
            "@echo off\n"
            f'set "_VENV_PY={venv_py}"\n'
            'if exist "%_VENV_PY%" (\n'
            '  "%_VENV_PY%" %*\n'
            "  exit /b %errorlevel%\n"
            ")\n"
            f'"{fallback}" %*\n'
        )
        _write_executable(local_bin / "python.cmd", shim)
        _write_executable(local_bin / "python3.cmd", shim)
        return

    venv_py = venv_dir / "bin" / "python"
    fallback = Path(sys.executable)
    shim = (
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        f'if [ -x "{venv_py}" ]; then\n'
        f'  exec "{venv_py}" "$@"\n'
        "fi\n"
        f'exec "{fallback}" "$@"\n'
    )
    _write_executable(local_bin / "python", shim)
    _write_executable(local_bin / "python3", shim)


def _sandbox_env(plugin_dir: Path, manifest: dict) -> dict[str, str]:
    """Build a clean, isolated environment for a plugin process.

    Like Pinokio, everything points inside the plugin's own folder:
      HOME      -> plugin_dir          (dotfiles, configs stay inside)
      TMPDIR    -> plugin_dir/.tmp     (temp files stay inside)
      XDG_*     -> plugin_dir/.cache   (caches stay inside)
      PATH      -> .venv/bin + system  (only plugin's own tools)

    Python deps are fully isolated in each plugin's own ``.venv``.
    The uv cache is **shared** across all plugins so identical wheels
    are stored on disk only once (hardlinked into each venv).

    Only explicit vars from the manifest's "env" dict are passed through.
    Nothing from the host os.environ leaks in.
    """
    plugin_str = str(plugin_dir)

    tmp_dir = plugin_dir / ".tmp"
    tmp_dir.mkdir(exist_ok=True)

    cache_dir = plugin_dir / ".cache"
    cache_dir.mkdir(exist_ok=True)

    _SHARED_UV_CACHE.mkdir(parents=True, exist_ok=True)

    venv_dir = plugin_dir / ".venv"
    if platform.system() == "Windows":
        venv_bin = venv_dir / "Scripts"
        local_bin = plugin_dir / "Scripts"
        shell_value = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
    else:
        venv_bin = venv_dir / "bin"
        local_bin = plugin_dir / "bin"
        shell_value = "/bin/bash"

    _ensure_python_shims(plugin_dir, venv_dir, local_bin)

    path_parts = []
    if venv_bin.is_dir():
        path_parts.append(str(venv_bin))
    path_parts.append(str(local_bin))
    path_parts.append(_SYSTEM_PATHS)

    env: dict[str, str] = {
        # Identity — everything lives in the plugin folder
        "HOME": plugin_str,
        "USER": "pocketpaw",
        "SHELL": shell_value,
        # Temp / cache — stays in plugin folder
        "TMPDIR": str(tmp_dir),
        "TEMP": str(tmp_dir),
        "TMP": str(tmp_dir),
        "XDG_CACHE_HOME": str(cache_dir),
        "XDG_CONFIG_HOME": plugin_str,
        "XDG_DATA_HOME": plugin_str,
        # PATH — plugin venv + minimal system
        "PATH": os.pathsep.join(path_parts),
        # Python — each plugin gets its own .venv for full isolation
        "VIRTUAL_ENV": str(venv_dir),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONUSERBASE": plugin_str,
        # uv — shared cache across all plugins so identical packages
        # are stored once on disk and hardlinked into each venv.
        # APFS/btrfs get copy-on-write clones; other FS get hardlinks.
        "UV_CACHE_DIR": str(_SHARED_UV_CACHE),
        "UV_LINK_MODE": "hardlink",
        # pip — install into the venv, not arbitrary dirs
        "PIP_PREFIX": str(venv_dir),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        # Locale
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
    }

    host_home = os.environ.get("HOME", "").strip()
    if host_home:
        # Allow selected backends (e.g. Codex OAuth) to access host-level auth stores
        # while still keeping plugin runtime HOME isolated by default.
        env["POCKETPAW_HOST_HOME"] = host_home

    # Layer manifest "env" on top (explicit config from pocketpaw.json)
    for key, val in (manifest.get("env") or {}).items():
        env[key] = str(val)

    # Port override
    port = manifest.get("port")
    if port:
        env["PORT"] = str(port)

    return env


def _sandbox_install_env(plugin_dir: Path, manifest: dict) -> dict[str, str]:
    """Environment for install phase — same sandbox but allows network tools.

    During install we need git, curl, uv from the host PATH so deps can
    be fetched.  Once installed, the runtime sandbox is tighter.

    The shared uv cache lets ``uv pip install`` hardlink packages that
    were already downloaded for other plugins — no re-download, no
    extra disk space.
    """
    env = _sandbox_env(plugin_dir, manifest)

    # During install, extend PATH with host paths so git/curl/uv work
    host_path = os.environ.get("PATH", "")
    env["PATH"] = env["PATH"] + os.pathsep + host_path

    # Let uv/pip find SSL certs from the host
    for key in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        val = os.environ.get(key)
        if val:
            env[key] = val

    return env


# ─── Helpers ─────────────────────────────────────────────────────────────


def get_plugins_dir() -> Path:
    """Get and ensure the plugins directory exists."""
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    return PLUGINS_DIR


def _resolve_chat_model_from_env(env: dict[str, Any]) -> str:
    backend = str(env.get("LLM_BACKEND", "g4f")).lower()
    if backend == "auto":
        return str(env.get("AUTO_G4F_MODEL", env.get("G4F_MODEL", "gpt-4o-mini")))
    if backend == "codex":
        return str(env.get("CODEX_MODEL", "gpt-5"))
    if backend == "qwen":
        return str(env.get("QWEN_MODEL", "qwen3-coder-plus"))
    if backend == "gemini":
        return str(env.get("GEMINI_MODEL", "gemini-2.5-flash"))
    return str(env.get("G4F_MODEL", "gpt-4o-mini"))


def _resolve_codex_bin(explicit_bin: str | None = None) -> str | None:
    if explicit_bin:
        candidate = Path(explicit_bin).expanduser()
        if candidate.exists():
            return str(candidate)

    path_bin = shutil.which("codex")
    if path_bin:
        return path_bin

    candidates: list[str] = []
    if platform.system() == "Darwin":
        candidates.extend(
            [
                "/opt/homebrew/bin/codex",
                "/usr/local/bin/codex",
            ]
        )
    elif platform.system() == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(str(Path(local_app_data) / "Programs" / "codex" / "codex.exe"))
    else:
        candidates.extend(["/usr/local/bin/codex", "/usr/bin/codex"])

    for candidate in candidates:
        if Path(candidate).exists():
            return candidate

    return None


def _resolve_qwen_command(explicit_bin: str | None = None) -> list[str] | None:
    if explicit_bin:
        candidate = Path(explicit_bin).expanduser()
        if candidate.exists():
            return [str(candidate)]

    qwen_bin = shutil.which("qwen")
    if qwen_bin:
        return [qwen_bin]

    candidates: list[str] = []
    if platform.system() == "Darwin":
        candidates.extend(
            [
                "/opt/homebrew/bin/qwen",
                "/usr/local/bin/qwen",
            ]
        )
    elif platform.system() == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(str(Path(local_app_data) / "Programs" / "qwen" / "qwen.exe"))
    else:
        candidates.extend(["/usr/local/bin/qwen", "/usr/bin/qwen"])

    for candidate in candidates:
        if Path(candidate).exists():
            return [candidate]

    npx_bin = shutil.which("npx")
    if npx_bin:
        return [npx_bin, "-y", "@qwen-code/qwen-code"]
    for candidate in ("/opt/homebrew/bin/npx", "/usr/local/bin/npx", "/usr/bin/npx"):
        if Path(candidate).exists():
            return [candidate, "-y", "@qwen-code/qwen-code"]

    return None


def _resolve_gemini_command(explicit_bin: str | None = None) -> list[str] | None:
    if explicit_bin:
        candidate = Path(explicit_bin).expanduser()
        if candidate.exists():
            return [str(candidate)]

    gemini_bin = shutil.which("gemini")
    if gemini_bin:
        return [gemini_bin]

    candidates: list[str] = []
    if platform.system() == "Darwin":
        candidates.extend(
            [
                "/opt/homebrew/bin/gemini",
                "/usr/local/bin/gemini",
            ]
        )
    elif platform.system() == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(str(Path(local_app_data) / "Programs" / "gemini" / "gemini.exe"))
    else:
        candidates.extend(["/usr/local/bin/gemini", "/usr/bin/gemini"])

    for candidate in candidates:
        if Path(candidate).exists():
            return [candidate]

    npx_bin = shutil.which("npx")
    if npx_bin:
        return [npx_bin, "-y", "@google/gemini-cli"]
    for candidate in ("/opt/homebrew/bin/npx", "/usr/local/bin/npx", "/usr/bin/npx"):
        if Path(candidate).exists():
            return [candidate, "-y", "@google/gemini-cli"]

    return None


def _parse_codex_auth_output_line(session: dict[str, Any], line: str) -> None:
    clean = line.strip()
    if not clean:
        return
    lines: list[str] = session.setdefault("lines", [])
    lines.append(clean)
    if len(lines) > 120:
        del lines[:-120]

    if not session.get("verification_uri"):
        match_url = re.search(r"https://auth\.openai\.com/codex/device", clean)
        if match_url:
            session["verification_uri"] = match_url.group(0)

    if not session.get("user_code"):
        match_code = re.search(r"\b[A-Z0-9]{4,}-[A-Z0-9]{4,}\b", clean)
        if match_code:
            session["user_code"] = match_code.group(0)


def _parse_qwen_auth_output_line(session: dict[str, Any], line: str) -> None:
    clean = line.strip()
    if not clean:
        return
    lines: list[str] = session.setdefault("lines", [])
    lines.append(clean)
    if len(lines) > 120:
        del lines[:-120]

    if not session.get("verification_uri"):
        match_url = re.search(r"https://chat\.qwen\.ai/authorize\?[^\s]+", clean)
        if match_url:
            verification_uri = match_url.group(0)
            session["verification_uri"] = verification_uri
            parsed = urllib.parse.urlparse(verification_uri)
            query = urllib.parse.parse_qs(parsed.query)
            user_code = (query.get("user_code") or [None])[0]
            if user_code and not session.get("user_code"):
                session["user_code"] = user_code

    if not session.get("user_code"):
        match_code = re.search(r"\b[A-Z0-9]{4,}-[A-Z0-9]{2,}\b", clean)
        if match_code:
            session["user_code"] = match_code.group(0)


def _parse_gemini_auth_output_line(session: dict[str, Any], line: str) -> None:
    clean = line.strip()
    if not clean:
        return
    lines: list[str] = session.setdefault("lines", [])
    lines.append(clean)
    if len(lines) > 120:
        del lines[:-120]

    if not session.get("verification_uri"):
        match_url = re.search(r"https://[^\s]+", clean)
        if match_url:
            session["verification_uri"] = match_url.group(0)


def _drain_codex_auth_output(session: dict[str, Any], timeout_seconds: float) -> None:
    q: queue.Queue[str | None] = session["queue"]
    process: subprocess.Popen[str] = session["process"]
    deadline = time.time() + max(timeout_seconds, 0.0)

    while time.time() < deadline:
        wait = min(0.2, max(0.0, deadline - time.time()))
        if wait <= 0:
            break
        try:
            item = q.get(timeout=wait)
        except queue.Empty:
            if process.poll() is not None:
                break
            continue
        if item is None:
            break
        _parse_codex_auth_output_line(session, item)

        if session.get("verification_uri") and session.get("user_code"):
            break


def _drain_qwen_auth_output(session: dict[str, Any], timeout_seconds: float) -> None:
    q: queue.Queue[str | None] = session["queue"]
    process: subprocess.Popen[str] = session["process"]
    deadline = time.time() + max(timeout_seconds, 0.0)

    while time.time() < deadline:
        wait = min(0.2, max(0.0, deadline - time.time()))
        if wait <= 0:
            break
        try:
            item = q.get(timeout=wait)
        except queue.Empty:
            if process.poll() is not None:
                break
            continue
        if item is None:
            break
        _parse_qwen_auth_output_line(session, item)

        if session.get("verification_uri") and session.get("user_code"):
            break


def _drain_gemini_auth_output(session: dict[str, Any], timeout_seconds: float) -> None:
    q: queue.Queue[str | None] = session["queue"]
    process: subprocess.Popen[str] = session["process"]
    deadline = time.time() + max(timeout_seconds, 0.0)

    while time.time() < deadline:
        wait = min(0.2, max(0.0, deadline - time.time()))
        if wait <= 0:
            break
        try:
            item = q.get(timeout=wait)
        except queue.Empty:
            if process.poll() is not None:
                break
            continue
        if item is None:
            break
        _parse_gemini_auth_output_line(session, item)

        if session.get("verification_uri"):
            break


def get_codex_auth_status() -> dict[str, Any]:
    codex_bin = _resolve_codex_bin()
    if not codex_bin:
        return {
            "ok": False,
            "logged_in": False,
            "message": "codex CLI not found on PATH",
        }

    try:
        result = subprocess.run(
            [codex_bin, "login", "status"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as e:
        return {
            "ok": False,
            "logged_in": False,
            "message": str(e) or "Failed to query codex login status",
        }

    message = (result.stdout or result.stderr or "").strip()
    combined = f"{result.stdout or ''}\n{result.stderr or ''}"
    logged_in = result.returncode == 0 and "Logged in" in combined
    return {
        "ok": logged_in,
        "logged_in": logged_in,
        "message": message or ("Logged in" if logged_in else "Not logged in"),
    }


def get_qwen_auth_status() -> dict[str, Any]:
    qwen_cmd = _resolve_qwen_command()
    if not qwen_cmd:
        return {
            "ok": False,
            "logged_in": False,
            "message": "qwen CLI not found (install @qwen-code/qwen-code)",
        }

    creds_path = Path.home() / ".qwen" / "oauth_creds.json"
    if not creds_path.exists():
        return {
            "ok": False,
            "logged_in": False,
            "message": "No Qwen OAuth credentials found",
            "credentials_path": str(creds_path),
        }

    try:
        creds = json.loads(creds_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {
            "ok": False,
            "logged_in": False,
            "message": str(e) or "Failed to read Qwen OAuth credentials",
            "credentials_path": str(creds_path),
        }

    access_token = str(creds.get("access_token", "")).strip()
    expiry_date = creds.get("expiry_date")
    logged_in = bool(access_token)
    expired = False
    if isinstance(expiry_date, (int, float)) and expiry_date > 0:
        expired = expiry_date <= (time.time() * 1000)
        if expired:
            logged_in = False

    resource = str(creds.get("resource_url", "")).strip()
    message = "Logged in" if logged_in else "OAuth credentials missing or expired"
    if expired:
        message = "OAuth credentials expired"
    if resource and logged_in:
        message = f"Logged in ({resource})"

    return {
        "ok": logged_in,
        "logged_in": logged_in,
        "expired": expired,
        "message": message,
        "credentials_path": str(creds_path),
    }


def get_gemini_auth_status() -> dict[str, Any]:
    gemini_cmd = _resolve_gemini_command()
    if not gemini_cmd:
        return {
            "ok": False,
            "logged_in": False,
            "message": "gemini CLI not found (install @google/gemini-cli)",
        }

    creds_path = Path.home() / ".gemini" / "oauth_creds.json"
    if not creds_path.exists():
        return {
            "ok": False,
            "logged_in": False,
            "message": "No Gemini OAuth credentials found",
            "credentials_path": str(creds_path),
        }

    try:
        creds = json.loads(creds_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {
            "ok": False,
            "logged_in": False,
            "message": str(e) or "Failed to read Gemini OAuth credentials",
            "credentials_path": str(creds_path),
        }

    access_token = str(creds.get("access_token", "")).strip()
    expiry_date = creds.get("expiry_date")
    logged_in = bool(access_token)
    expired = False
    if isinstance(expiry_date, (int, float)) and expiry_date > 0:
        expired = expiry_date <= (time.time() * 1000)
        if expired:
            logged_in = False

    message = "Logged in with Google" if logged_in else "OAuth credentials missing or expired"
    if expired:
        message = "OAuth credentials expired"

    return {
        "ok": logged_in,
        "logged_in": logged_in,
        "expired": expired,
        "message": message,
        "credentials_path": str(creds_path),
    }


def start_codex_device_auth() -> dict[str, Any]:
    with _codex_auth_lock:
        for sid, session in _codex_auth_sessions.items():
            proc = session.get("process")
            if isinstance(proc, subprocess.Popen) and proc.poll() is None:
                _drain_codex_auth_output(session, timeout_seconds=0.2)
                return {
                    "ok": True,
                    "status": "pending",
                    "session_id": sid,
                    "verification_uri": session.get("verification_uri"),
                    "user_code": session.get("user_code"),
                    "message": "Codex OAuth is already in progress",
                }

    codex_bin = _resolve_codex_bin()
    if not codex_bin:
        return {"ok": False, "status": "error", "message": "codex CLI not found on PATH"}

    try:
        process = subprocess.Popen(
            [codex_bin, "login", "--device-auth"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except Exception as e:
        return {"ok": False, "status": "error", "message": str(e) or "Failed to start OAuth"}

    read_queue: queue.Queue[str | None] = queue.Queue()

    def _reader() -> None:
        stream = process.stdout
        if stream is None:
            read_queue.put(None)
            return
        try:
            for raw_line in stream:
                read_queue.put(raw_line.rstrip("\n"))
        finally:
            read_queue.put(None)

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()

    session_id = uuid.uuid4().hex
    session: dict[str, Any] = {
        "process": process,
        "queue": read_queue,
        "thread": thread,
        "lines": [],
        "verification_uri": None,
        "user_code": None,
        "started_at": time.time(),
    }
    with _codex_auth_lock:
        _codex_auth_sessions[session_id] = session

    _drain_codex_auth_output(session, timeout_seconds=4.0)

    return {
        "ok": True,
        "status": "pending" if process.poll() is None else "completed",
        "session_id": session_id,
        "verification_uri": session.get("verification_uri"),
        "user_code": session.get("user_code"),
        "message": (
            "Open verification URL and enter the one-time code"
            if session.get("verification_uri") and session.get("user_code")
            else "OAuth started. Waiting for login to complete."
        ),
    }


def start_qwen_device_auth() -> dict[str, Any]:
    with _qwen_auth_lock:
        for sid, session in _qwen_auth_sessions.items():
            proc = session.get("process")
            if isinstance(proc, subprocess.Popen) and proc.poll() is None:
                _drain_qwen_auth_output(session, timeout_seconds=0.2)
                return {
                    "ok": True,
                    "status": "pending",
                    "session_id": sid,
                    "verification_uri": session.get("verification_uri"),
                    "user_code": session.get("user_code"),
                    "message": "Qwen OAuth is already in progress",
                }

    qwen_cmd = _resolve_qwen_command()
    if not qwen_cmd:
        return {
            "ok": False,
            "status": "error",
            "message": "qwen CLI not found (install @qwen-code/qwen-code)",
        }

    try:
        process = subprocess.Popen(
            [
                *qwen_cmd,
                "--auth-type",
                "qwen-oauth",
                "--output-format",
                "json",
                "Reply with exactly: pong",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except Exception as e:
        return {"ok": False, "status": "error", "message": str(e) or "Failed to start OAuth"}

    read_queue: queue.Queue[str | None] = queue.Queue()

    def _reader() -> None:
        stream = process.stdout
        if stream is None:
            read_queue.put(None)
            return
        try:
            for raw_line in stream:
                read_queue.put(raw_line.rstrip("\n"))
        finally:
            read_queue.put(None)

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()

    session_id = uuid.uuid4().hex
    session: dict[str, Any] = {
        "process": process,
        "queue": read_queue,
        "thread": thread,
        "lines": [],
        "verification_uri": None,
        "user_code": None,
        "started_at": time.time(),
    }
    with _qwen_auth_lock:
        _qwen_auth_sessions[session_id] = session

    _drain_qwen_auth_output(session, timeout_seconds=4.0)

    return {
        "ok": True,
        "status": "pending" if process.poll() is None else "completed",
        "session_id": session_id,
        "verification_uri": session.get("verification_uri"),
        "user_code": session.get("user_code"),
        "message": (
            "Open Qwen authorization URL and complete sign-in"
            if session.get("verification_uri")
            else "OAuth started. Waiting for login to complete."
        ),
    }


def start_gemini_device_auth() -> dict[str, Any]:
    with _gemini_auth_lock:
        for sid, session in _gemini_auth_sessions.items():
            proc = session.get("process")
            if isinstance(proc, subprocess.Popen) and proc.poll() is None:
                _drain_gemini_auth_output(session, timeout_seconds=0.2)
                return {
                    "ok": True,
                    "status": "pending",
                    "session_id": sid,
                    "verification_uri": session.get("verification_uri"),
                    "user_code": None,
                    "message": "Gemini OAuth is already in progress",
                }

    gemini_cmd = _resolve_gemini_command()
    if not gemini_cmd:
        return {
            "ok": False,
            "status": "error",
            "message": "gemini CLI not found (install @google/gemini-cli)",
        }

    env = dict(os.environ)
    env["GOOGLE_GENAI_USE_GCA"] = "true"

    try:
        process = subprocess.Popen(
            [
                *gemini_cmd,
                "-p",
                "Reply with exactly: pong",
                "--output-format",
                "json",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
    except Exception as e:
        return {"ok": False, "status": "error", "message": str(e) or "Failed to start OAuth"}

    if process.stdin is not None:
        try:
            process.stdin.write("y\n")
            process.stdin.flush()
            process.stdin.close()
        except Exception:
            pass

    read_queue: queue.Queue[str | None] = queue.Queue()

    def _reader() -> None:
        stream = process.stdout
        if stream is None:
            read_queue.put(None)
            return
        try:
            for raw_line in stream:
                read_queue.put(raw_line.rstrip("\n"))
        finally:
            read_queue.put(None)

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()

    session_id = uuid.uuid4().hex
    session: dict[str, Any] = {
        "process": process,
        "queue": read_queue,
        "thread": thread,
        "lines": [],
        "verification_uri": None,
        "user_code": None,
        "started_at": time.time(),
    }
    with _gemini_auth_lock:
        _gemini_auth_sessions[session_id] = session

    _drain_gemini_auth_output(session, timeout_seconds=4.0)

    return {
        "ok": True,
        "status": "pending" if process.poll() is None else "completed",
        "session_id": session_id,
        "verification_uri": session.get("verification_uri"),
        "user_code": None,
        "message": (
            "Follow the browser prompt and complete Google sign-in"
            if not session.get("verification_uri")
            else "Open Gemini authorization URL and complete sign-in"
        ),
    }


def get_codex_device_auth_status(session_id: str) -> dict[str, Any]:
    with _codex_auth_lock:
        session = _codex_auth_sessions.get(session_id)
    if not session:
        return {
            "ok": False,
            "status": "not_found",
            "message": "OAuth session not found",
        }

    process: subprocess.Popen[str] = session["process"]
    _drain_codex_auth_output(session, timeout_seconds=0.2)

    rc = process.poll()
    lines: list[str] = session.get("lines", [])
    last_message = lines[-1] if lines else ""

    if rc is None:
        return {
            "ok": True,
            "status": "pending",
            "session_id": session_id,
            "verification_uri": session.get("verification_uri"),
            "user_code": session.get("user_code"),
            "message": "Waiting for browser authorization",
            "last_message": last_message,
        }

    status = "completed" if rc == 0 else "error"
    result = {
        "ok": rc == 0,
        "status": status,
        "session_id": session_id,
        "verification_uri": session.get("verification_uri"),
        "user_code": session.get("user_code"),
        "message": (
            "Codex OAuth login completed"
            if rc == 0
            else (last_message or f"codex login exited with code {rc}")
        ),
        "last_message": last_message,
    }
    if rc is not None:
        with _codex_auth_lock:
            _codex_auth_sessions.pop(session_id, None)
    return result


def get_qwen_device_auth_status(session_id: str) -> dict[str, Any]:
    with _qwen_auth_lock:
        session = _qwen_auth_sessions.get(session_id)
    if not session:
        return {
            "ok": False,
            "status": "not_found",
            "message": "OAuth session not found",
        }

    process: subprocess.Popen[str] = session["process"]
    _drain_qwen_auth_output(session, timeout_seconds=0.2)

    rc = process.poll()
    lines: list[str] = session.get("lines", [])
    last_message = lines[-1] if lines else ""

    if rc is None:
        return {
            "ok": True,
            "status": "pending",
            "session_id": session_id,
            "verification_uri": session.get("verification_uri"),
            "user_code": session.get("user_code"),
            "message": "Waiting for browser authorization",
            "last_message": last_message,
        }

    auth_status = get_qwen_auth_status()
    status = "completed" if rc == 0 and auth_status.get("logged_in") else "error"
    result = {
        "ok": status == "completed",
        "status": status,
        "session_id": session_id,
        "verification_uri": session.get("verification_uri"),
        "user_code": session.get("user_code"),
        "message": (
            "Qwen OAuth login completed"
            if status == "completed"
            else (auth_status.get("message") or last_message or f"qwen login exited with code {rc}")
        ),
        "last_message": last_message,
    }
    with _qwen_auth_lock:
        _qwen_auth_sessions.pop(session_id, None)
    return result


def get_gemini_device_auth_status(session_id: str) -> dict[str, Any]:
    with _gemini_auth_lock:
        session = _gemini_auth_sessions.get(session_id)
    if not session:
        return {
            "ok": False,
            "status": "not_found",
            "message": "OAuth session not found",
        }

    process: subprocess.Popen[str] = session["process"]
    _drain_gemini_auth_output(session, timeout_seconds=0.2)

    rc = process.poll()
    lines: list[str] = session.get("lines", [])
    last_message = lines[-1] if lines else ""

    if rc is None:
        return {
            "ok": True,
            "status": "pending",
            "session_id": session_id,
            "verification_uri": session.get("verification_uri"),
            "user_code": None,
            "message": "Waiting for browser authorization",
            "last_message": last_message,
        }

    auth_status = get_gemini_auth_status()
    status = "completed" if rc == 0 and auth_status.get("logged_in") else "error"
    result = {
        "ok": status == "completed",
        "status": status,
        "session_id": session_id,
        "verification_uri": session.get("verification_uri"),
        "user_code": None,
        "message": (
            "Gemini OAuth login completed"
            if status == "completed"
            else (
                auth_status.get("message") or last_message or f"gemini login exited with code {rc}"
            )
        ),
        "last_message": last_message,
    }
    with _gemini_auth_lock:
        _gemini_auth_sessions.pop(session_id, None)
    return result


def _read_manifest(plugin_dir: Path) -> dict | None:
    """Read pocketpaw.json manifest from a plugin directory."""
    manifest_path = plugin_dir / "pocketpaw.json"
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read manifest at %s: %s", manifest_path, e)
        return None


def _get_effective_manifest(plugin_id: str, manifest: dict) -> dict:
    """Merge builtin manifest over disk manifest for web_view fields.

    Builtins may have newer manifest fields (e.g. web_view) in code than
    on disk. This ensures builtins always get the latest web_view config
    without requiring re-install.
    """
    try:
        from pocketpaw.ai_ui.builtins import get_registry

        registry = get_registry()
        builtin_def = registry.get(plugin_id)
        if builtin_def and "manifest" in builtin_def:
            bm = builtin_def["manifest"]
            merged = dict(manifest)
            if "web_view" in bm:
                merged["web_view"] = bm["web_view"]
            if "web_view_path" in bm:
                merged["web_view_path"] = bm["web_view_path"]
            return merged
    except Exception:
        pass
    return manifest


def _refresh_builtin_overlay_files(plugin_id: str, plugin_dir: Path) -> None:
    """Refresh overlay files for installed built-ins without requiring reinstall."""
    try:
        from pocketpaw.ai_ui.builtins import get_registry

        builtin_def = get_registry().get(plugin_id)
        if not builtin_def:
            return

        files = builtin_def.get("files") or {}
        for filename, content in files.items():
            if not isinstance(filename, str) or not isinstance(content, str):
                continue
            path = plugin_dir / filename
            try:
                if path.exists() and path.read_text(encoding="utf-8") == content:
                    continue
            except OSError:
                logger.debug("Unable to read existing built-in overlay '%s'", path, exc_info=True)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            except OSError:
                logger.warning(
                    "Failed to refresh built-in overlay file '%s' for plugin '%s'",
                    filename,
                    plugin_id,
                    exc_info=True,
                )
    except Exception:
        logger.debug("Failed to refresh built-in overlay files for '%s'", plugin_id, exc_info=True)


# ─── PID persistence ────────────────────────────────────────────────────


def _write_pid(plugin_dir: Path, pid: int) -> None:
    (plugin_dir / _PID_FILENAME).write_text(str(pid), encoding="utf-8")


def _read_pid(plugin_dir: Path) -> int | None:
    pid_path = plugin_dir / _PID_FILENAME
    if not pid_path.exists():
        return None
    try:
        return int(pid_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def _tail_file(path: Path, lines: int = 20) -> str:
    """Return the last N lines from a text file, or empty string."""
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    chunk = text.strip().splitlines()[-lines:]
    return "\n".join(chunk).strip()


def _is_shell_command(cmd: str) -> bool:
    tokens = [t.lower() for t in cmd.strip().split() if t.strip()]
    if not tokens:
        return False
    if tokens[0] in {"bash", "sh"}:
        return True
    return any(token.endswith(".sh") for token in tokens)


def _extract_exec_command(script_path: Path) -> str | None:
    """Extract a trailing `exec ...` command from a shell script, if present."""
    try:
        lines = script_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None

    for raw in reversed(lines):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("exec "):
            cmd = line[5:].strip()
            return cmd or None
    return None


def _resolve_phase_command(plugin_dir: Path, manifest: dict | None, phase: str) -> str:
    """Resolve install/start/stop command with cross-platform fallbacks.

    Priority:
    1) `pocketpaw_<phase>.py` wrapper (universal)
    2) manifest command
    3) `<phase>.sh` script
    """
    wrapper = plugin_dir / f"pocketpaw_{phase}.py"
    if wrapper.exists():
        return f"python {wrapper.name}"

    cmd = str((manifest or {}).get(phase) or "").strip()
    if cmd:
        # On Windows, allow shell scripts when Git Bash exists.
        if platform.system() == "Windows" and _is_shell_command(cmd):
            bash = shutil.which("bash")
            if bash:
                script = plugin_dir / f"{phase}.sh"
                if script.exists():
                    return f'"{bash}" {script.name}'
            script = plugin_dir / f"{phase}.sh"
            if script.exists():
                extracted = _extract_exec_command(script)
                if extracted:
                    return extracted
            return ""
        return cmd

    script = plugin_dir / f"{phase}.sh"
    if script.exists():
        if platform.system() == "Windows":
            bash = shutil.which("bash")
            if bash:
                return f'"{bash}" {script.name}'
            extracted = _extract_exec_command(script)
            if extracted:
                return extracted
            return ""
        return f"bash {script.name}"

    return ""


def _clear_pid(plugin_dir: Path) -> None:
    pid_path = plugin_dir / _PID_FILENAME
    pid_path.unlink(missing_ok=True)


def _is_pid_alive(pid: int) -> bool:
    """Check whether an OS process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (ProcessLookupError, OSError):
        return False


def _is_port_listening(port: int) -> bool:
    """Check if something is listening on localhost:port (e.g. after uvicorn reload)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.connect(("127.0.0.1", port))
            return True
    except (OSError, TypeError, ValueError):
        return False


def _get_pid_on_port(port: int) -> int | None:
    """Return PID of process listening on port, or None."""
    if platform.system() == "Windows":
        try:
            proc = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in proc.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line.upper():
                    parts = line.split()
                    if parts:
                        return int(parts[-1])
        except (ValueError, subprocess.TimeoutExpired, OSError):
            pass
        return None
    try:
        proc = subprocess.run(
            ["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        out = (proc.stdout or "").strip()
        if out:
            return int(out.splitlines()[0].strip())
    except (ValueError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def _pid_cwd(pid: int) -> Path | None:
    """Best-effort process cwd lookup for ownership checks."""
    if platform.system() == "Windows":
        return None
    try:
        proc = subprocess.run(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    for line in (proc.stdout or "").splitlines():
        if line.startswith("n"):
            raw_path = line[1:].strip()
            if raw_path:
                return Path(raw_path).resolve()
    return None


def _pid_belongs_to_plugin(pid: int, plugin_dir: Path) -> bool:
    """Return True when process cwd points inside the plugin directory."""
    cwd = _pid_cwd(pid)
    if cwd is None:
        return False
    try:
        plugin_root = plugin_dir.resolve()
    except OSError:
        return False
    try:
        cwd.relative_to(plugin_root)
        return True
    except ValueError:
        return False


def _is_port_unique_to_plugin(plugin_id: str, port: int) -> bool:
    """Return True when only this plugin is configured to use ``port``."""
    plugins_dir = get_plugins_dir()
    seen_self = False
    for item in plugins_dir.iterdir():
        if not item.is_dir():
            continue
        manifest = _read_manifest(item)
        if not manifest:
            continue
        try:
            plugin_port = int(manifest.get("port") or 0)
        except (TypeError, ValueError):
            continue
        if plugin_port != port:
            continue
        if item.name == plugin_id:
            seen_self = True
            continue
        return False
    return seen_self


def _is_plugin_running(plugin_id: str, plugin_dir: Path) -> bool:
    """Check running state: in-memory process, PID file, then port fallback.

    Port fallback handles uvicorn --reload: the tracked PID exits when uvicorn
    restarts, but a new process listens on the same port.
    """
    proc = _running_processes.get(plugin_id)
    if proc is not None and proc.returncode is None:
        return True

    pid = _read_pid(plugin_dir)
    if pid is not None and _is_pid_alive(pid):
        return True

    if pid is not None:
        _clear_pid(plugin_dir)

    # Fallback: PID dead but port may be in use (e.g. uvicorn reload respawned)
    manifest = _read_manifest(plugin_dir)
    if manifest:
        port = manifest.get("port")
        try:
            p = int(port) if port is not None else 0
            if p > 0 and _is_port_unique_to_plugin(plugin_id, p) and _is_port_listening(p):
                return True
        except (TypeError, ValueError):
            pass

    return False


def _read_readme(plugin_dir: Path) -> str | None:
    """Read README from plugin directory."""
    for name in ("README.md", "readme.md", "README.txt", "README"):
        readme_path = plugin_dir / name
        if readme_path.exists():
            try:
                return readme_path.read_text(encoding="utf-8")[:5000]
            except OSError:
                pass
    return None


# ─── List / Get ──────────────────────────────────────────────────────────


def list_plugins() -> list[dict[str, Any]]:
    """List all installed plugins with their manifests and status."""
    plugins_dir = get_plugins_dir()
    plugins = []

    for item in sorted(plugins_dir.iterdir()):
        if not item.is_dir():
            continue
        manifest = _read_manifest(item)
        if manifest is None:
            continue

        plugin_id = item.name
        manifest = _get_effective_manifest(plugin_id, manifest)
        running = _is_plugin_running(plugin_id, item)

        openapi_file = manifest.get("openapi")
        has_openapi = (running and manifest.get("port")) or (
            openapi_file and (item / openapi_file).exists()
        )

        plugins.append(
            {
                "id": plugin_id,
                "name": manifest.get("name", plugin_id),
                "description": manifest.get("description", ""),
                "icon": manifest.get("icon", "package"),
                "version": manifest.get("version", "0.0.0"),
                "port": manifest.get("port"),
                "status": "running" if running else "stopped",
                "path": str(item),
                "start_cmd": manifest.get("start", ""),
                "has_install": ((item / "install.sh").exists() or bool(manifest.get("install"))),
                "requires": manifest.get("requires", []),
                "env": manifest.get("env", {}),
                "openapi": openapi_file if has_openapi else None,
                "web_view": manifest.get("web_view", "iframe"),
                "web_view_path": manifest.get("web_view_path", "/"),
            }
        )

    return plugins


def get_plugin(plugin_id: str) -> dict | None:
    """Get a single plugin's details."""
    plugin_dir = get_plugins_dir() / plugin_id
    if not plugin_dir.is_dir():
        return None
    manifest = _read_manifest(plugin_dir)
    if manifest is None:
        return None

    manifest = _get_effective_manifest(plugin_id, manifest)
    running = _is_plugin_running(plugin_id, plugin_dir)

    openapi_file = manifest.get("openapi")
    has_openapi = (running and manifest.get("port")) or (
        openapi_file and (plugin_dir / openapi_file).exists()
    )

    return {
        "id": plugin_id,
        "name": manifest.get("name", plugin_id),
        "description": manifest.get("description", ""),
        "icon": manifest.get("icon", "package"),
        "version": manifest.get("version", "0.0.0"),
        "port": manifest.get("port"),
        "status": "running" if running else "stopped",
        "path": str(plugin_dir),
        "start_cmd": manifest.get("start", ""),
        "has_install": ((plugin_dir / "install.sh").exists() or bool(manifest.get("install"))),
        "requires": manifest.get("requires", []),
        "env": manifest.get("env", {}),
        "openapi": openapi_file if has_openapi else None,
        "readme": _read_readme(plugin_dir),
        "web_view": manifest.get("web_view", "iframe"),
        "web_view_path": manifest.get("web_view_path", "/"),
    }


def get_plugin_config(plugin_id: str) -> dict[str, Any] | None:
    """Get a plugin's config (env) from pocketpaw.json."""
    if ".." in plugin_id or "/" in plugin_id or "\\" in plugin_id:
        raise ValueError("Invalid plugin ID")

    plugin_dir = get_plugins_dir() / plugin_id
    if not plugin_dir.is_dir():
        return None
    manifest = _read_manifest(plugin_dir)
    if manifest is None:
        return None
    return dict(manifest.get("env", {}))


def update_plugin_config(plugin_id: str, config: dict[str, str]) -> dict:
    """Update a plugin's config (env) in pocketpaw.json.

    Merges config into manifest.env. Restart required for changes to apply.
    """
    if ".." in plugin_id or "/" in plugin_id or "\\" in plugin_id:
        raise ValueError("Invalid plugin ID")

    plugin_dir = get_plugins_dir() / plugin_id
    manifest_path = plugin_dir / "pocketpaw.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Plugin '{plugin_id}' not found")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    env = manifest.get("env", {})
    for key, val in config.items():
        if val is None or val == "":
            env.pop(key, None)
        else:
            env[key] = str(val)
    manifest["env"] = env
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"status": "ok", "config": dict(env)}


def test_plugin_connection(
    plugin_id: str, host: str | None = None, port: int | None = None
) -> dict:
    """Call POST /v1/chat/completions with a ping message. Returns { ok: bool, message: str }."""
    if ".." in plugin_id or "/" in plugin_id or "\\" in plugin_id:
        raise ValueError("Invalid plugin ID")

    plugin_dir = get_plugins_dir() / plugin_id
    manifest = _read_manifest(plugin_dir)
    if manifest is None:
        raise FileNotFoundError(f"Plugin '{plugin_id}' not found")

    env = manifest.get("env", {})
    backend = str(env.get("LLM_BACKEND", "g4f")).lower()
    h = host or env.get("HOST", "0.0.0.0")
    # Use 127.0.0.1 for connect; 0.0.0.0 is bind-only
    if h in ("0.0.0.0", ""):
        h = "127.0.0.1"
    p = port if port is not None else int(env.get("PORT", "8000"))
    url = f"http://{h}:{p}/v1/chat/completions"

    payload = {
        "model": _resolve_chat_model_from_env(env),
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": False,
    }

    try:
        import httpx

        timeout = 60.0 if backend in {"auto", "codex", "qwen", "gemini"} else 15.0
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices") or []
                if choices and choices[0].get("message"):
                    return {"ok": True, "message": "Chat OK"}
                return {"ok": False, "message": "Empty chat response"}
            # Capture 4xx/5xx body for debugging
            try:
                err = resp.json()
                msg = err.get("detail") or err.get("error", {}).get("message") or str(err)
            except Exception:
                msg = resp.text[:200] if resp.text else ""
            return {
                "ok": False,
                "message": f"HTTP {resp.status_code}: {msg}" if msg else f"HTTP {resp.status_code}",
            }
    except Exception as e:
        return {"ok": False, "message": str(e) or "Chat ping failed"}


def fetch_plugin_models(
    plugin_id: str, host: str | None = None, port: int | None = None
) -> list[dict]:
    """Fetch /v1/models from a running plugin. Returns list of { id, ... }. Empty if not running."""
    if ".." in plugin_id or "/" in plugin_id or "\\" in plugin_id:
        raise ValueError("Invalid plugin ID")

    plugin_dir = get_plugins_dir() / plugin_id
    manifest = _read_manifest(plugin_dir)
    if manifest is None:
        raise FileNotFoundError(f"Plugin '{plugin_id}' not found")

    env = manifest.get("env", {})
    h = host or env.get("HOST", "0.0.0.0")
    if h in ("0.0.0.0", ""):
        h = "127.0.0.1"
    p = port if port is not None else int(env.get("PORT", "8000"))
    url = f"http://{h}:{p}/v1/models"

    try:
        import httpx

        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
            return data.get("data") or []
    except Exception:
        return []


def fetch_plugin_providers(
    plugin_id: str, host: str | None = None, port: int | None = None
) -> list[dict]:
    """Fetch /v1/providers from a running plugin.

    Returns list of { id, url, models, ... }. Empty if not running.
    """
    if ".." in plugin_id or "/" in plugin_id or "\\" in plugin_id:
        raise ValueError("Invalid plugin ID")

    plugin_dir = get_plugins_dir() / plugin_id
    manifest = _read_manifest(plugin_dir)
    if manifest is None:
        raise FileNotFoundError(f"Plugin '{plugin_id}' not found")

    env = manifest.get("env", {})
    h = host or env.get("HOST", "0.0.0.0")
    if h in ("0.0.0.0", ""):
        h = "127.0.0.1"
    p = port if port is not None else int(env.get("PORT", "8000"))
    url = f"http://{h}:{p}/v1/providers"

    try:
        import httpx

        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
            return data.get("data") or []
    except Exception:
        return []


def chat_completion_proxy(plugin_id: str, messages: list[dict]) -> dict:
    """Forward chat completion request to the plugin. Returns OpenAI-format response."""
    if ".." in plugin_id or "/" in plugin_id or "\\" in plugin_id:
        raise ValueError("Invalid plugin ID")

    plugin_dir = get_plugins_dir() / plugin_id
    manifest = _read_manifest(plugin_dir)
    if manifest is None:
        raise FileNotFoundError(f"Plugin '{plugin_id}' not found")

    env = manifest.get("env", {})
    h = env.get("HOST", "0.0.0.0")
    if h in ("0.0.0.0", ""):
        h = "127.0.0.1"
    p = int(env.get("PORT", "8000"))
    url = f"http://{h}:{p}/v1/chat/completions"

    payload = {
        "model": _resolve_chat_model_from_env(env),
        "messages": messages,
        "stream": False,
    }

    import httpx

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


def _chat_history_path(plugin_id: str) -> Path:
    """Path to chat history file for a plugin."""
    base = Path.home() / ".pocketpaw" / "ai-ui" / "chat"
    base.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in plugin_id)
    return base / f"{safe_id}.json"


def get_chat_history(plugin_id: str) -> list[dict]:
    """Load chat history for a plugin. Returns list of {role, content}."""
    if ".." in plugin_id or "/" in plugin_id or "\\" in plugin_id:
        raise ValueError("Invalid plugin ID")
    path = _chat_history_path(plugin_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_chat_history(plugin_id: str, messages: list[dict]) -> None:
    """Save chat history for a plugin."""
    if ".." in plugin_id or "/" in plugin_id or "\\" in plugin_id:
        raise ValueError("Invalid plugin ID")
    path = _chat_history_path(plugin_id)
    path.write_text(json.dumps(messages, indent=2), encoding="utf-8")


# ─── Install ─────────────────────────────────────────────────────────────


async def install_plugin(source: str) -> dict:
    """Install a plugin from a git URL or local path.

    Source can be:
      - Git URL: https://github.com/user/repo.git
      - Git shorthand: user/repo
      - Local path: /path/to/plugin
    """
    plugins_dir = get_plugins_dir()

    if ".." in source or ";" in source or "|" in source or "&" in source:
        raise ValueError("That doesn't look like a valid app URL. Try something like: user/repo")

    # Built-in curated plugins
    if source.startswith("builtin:"):
        app_id = source.split(":", 1)[1]
        from pocketpaw.ai_ui.builtins import get_install_block_reason, install_builtin

        reason = get_install_block_reason(app_id)
        if reason:
            raise ValueError(reason)

        return await install_builtin(app_id, plugins_dir)

    # Local path
    src_path = Path(source).expanduser()
    if src_path.is_dir():
        manifest = _read_manifest(src_path)
        if manifest is None:
            raise ValueError(
                "This folder is missing a pocketpaw.json config file. "
                "PocketPaw plugins need this file to know how to "
                "install and run the app."
            )
        plugin_id = src_path.name
        dest = plugins_dir / plugin_id
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src_path, dest)
        return {
            "status": "ok",
            "message": f"{manifest['name']} has been added!",
            "plugin_id": plugin_id,
        }

    # Git URL
    git_url = source
    if not git_url.startswith(("http://", "https://", "git@")):
        parts = source.split("/")
        if len(parts) == 2:
            git_url = f"https://github.com/{source}.git"
        else:
            raise ValueError(
                "That doesn't look right. Try entering a GitHub URL "
                "like: user/repo or https://github.com/user/repo"
            )

    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "clone",
            "--depth=1",
            git_url,
            tmpdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr_out = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode != 0:
            err = stderr_out.decode(errors="replace").strip()
            if "not found" in err.lower() or "404" in err:
                raise RuntimeError("Couldn't find that app. Double-check the URL and try again.")
            raise RuntimeError(
                "Couldn't download the app. Please check your internet connection and try again."
            )

        tmp = Path(tmpdir)
        manifest = _read_manifest(tmp)

        if manifest is None:
            raise ValueError(
                "This repository doesn't seem to be a PocketPaw plugin. "
                "It's missing the required `pocketpaw.json` file."
            )

        repo_name = git_url.rstrip("/").rstrip(".git").split("/")[-1]
        plugin_id = repo_name
        dest = plugins_dir / plugin_id
        if dest.exists():
            shutil.rmtree(dest)

        shutil.copytree(tmp, dest, dirs_exist_ok=True)
        git_dir = dest / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)

    # Run install in sandboxed env (with network access for deps)
    install_cmd = _resolve_phase_command(dest, manifest, "install")
    sandbox_env = _sandbox_install_env(dest, manifest)

    if install_cmd:
        logger.info("Running install command for '%s': %s", plugin_id, install_cmd)
        proc = await asyncio.create_subprocess_shell(
            install_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(dest),
            env=sandbox_env,
        )
        await asyncio.wait_for(proc.communicate(), timeout=300)

    return {
        "status": "ok",
        "message": f"{manifest['name']} has been added!",
        "plugin_id": plugin_id,
    }


async def install_plugin_from_zip(zip_bytes: bytes) -> dict:
    """Install a plugin from an uploaded zip file.

    The zip must contain either:
      - A top-level folder with pocketpaw.json inside (e.g. my-app/pocketpaw.json)
      - pocketpaw.json at the root of the zip
    """
    import tempfile

    plugins_dir = get_plugins_dir()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
                zf.extractall(tmp)
        except zipfile.BadZipFile as e:
            raise ValueError(
                "That doesn't look like a valid zip file. "
                "Please upload a .zip containing a PocketPaw plugin."
            ) from e

        # Find plugin root: single top-level dir with manifest, or root with manifest
        manifest = _read_manifest(tmp)
        if manifest is not None:
            plugin_root = tmp
            plugin_id = manifest.get("name", "plugin")
            # Sanitize: alphanumeric + hyphen
            plugin_id = "".join(c if c.isalnum() or c == "-" else "_" for c in plugin_id)
            if not plugin_id:
                plugin_id = "uploaded-plugin"
        else:
            subdirs = [d for d in tmp.iterdir() if d.is_dir()]
            if len(subdirs) != 1:
                raise ValueError(
                    "Zip must contain a single folder with pocketpaw.json, "
                    "or pocketpaw.json at the root."
                )
            plugin_root = subdirs[0]
            manifest = _read_manifest(plugin_root)
            if manifest is None:
                raise ValueError(
                    "That folder is missing a pocketpaw.json config file. "
                    "PocketPaw plugins need this file to know how to install and run the app."
                )
            plugin_id = plugin_root.name

        if ".." in plugin_id or "/" in plugin_id or "\\" in plugin_id:
            raise ValueError("Invalid plugin ID from zip")

        dest = plugins_dir / plugin_id
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(plugin_root, dest)
        # Copy done while temp dir still exists

    # Run install in sandboxed env
    install_cmd = _resolve_phase_command(dest, manifest, "install")
    sandbox_env = _sandbox_install_env(dest, manifest)

    if install_cmd:
        logger.info("Running install command for '%s': %s", plugin_id, install_cmd)
        proc = await asyncio.create_subprocess_shell(
            install_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(dest),
            env=sandbox_env,
        )
        await asyncio.wait_for(proc.communicate(), timeout=300)

    return {
        "status": "ok",
        "message": f"{manifest['name']} has been added!",
        "plugin_id": plugin_id,
    }


# ─── Launch / Stop ───────────────────────────────────────────────────────


async def launch_plugin(plugin_id: str) -> dict:
    """Launch a plugin inside its sandboxed workspace."""
    plugin_dir = get_plugins_dir() / plugin_id

    if _is_plugin_running(plugin_id, plugin_dir):
        return {
            "status": "already_running",
            "message": f"Plugin '{plugin_id}' is already running",
        }

    manifest = _read_manifest(plugin_dir)
    if manifest is None:
        raise ValueError(f"Plugin '{plugin_id}' not found or missing manifest")

    _refresh_builtin_overlay_files(plugin_id, plugin_dir)

    start_cmd = _resolve_phase_command(plugin_dir, manifest, "start")
    if not start_cmd:
        raise ValueError(f"Plugin '{plugin_id}' has no start command")

    env = _sandbox_env(plugin_dir, manifest)
    if plugin_id == "wan2gp" and platform.system() == "Darwin":
        env["WAN2GP_ALLOW_MAC"] = "1"

    logger.info(
        "Launching plugin '%s': %s (sandboxed in %s)",
        plugin_id,
        start_cmd,
        plugin_dir,
    )

    log_path = plugin_dir / _LOG_FILENAME
    log_file = log_path.open("w", encoding="utf-8")

    spawn_kwargs: dict[str, Any] = {
        "stdout": log_file,
        "stderr": log_file,
        "cwd": str(plugin_dir),
        "env": env,
    }
    if platform.system() != "Windows":
        spawn_kwargs["preexec_fn"] = os.setsid
    proc = await asyncio.create_subprocess_shell(start_cmd, **spawn_kwargs)

    log_file.close()

    _running_processes[plugin_id] = proc
    _write_pid(plugin_dir, proc.pid)

    # Catch immediate failures (bad command, missing deps, crash on startup)
    # so UI doesn't report "launched" for a dead process.
    await asyncio.sleep(0.35)
    if proc.returncode is not None:
        _running_processes.pop(plugin_id, None)
        _clear_pid(plugin_dir)
        tail = _tail_file(log_path, lines=25)
        detail = (
            f"Plugin '{plugin_id}' failed to start (exit code {proc.returncode})."
            if proc.returncode != 0
            else f"Plugin '{plugin_id}' exited immediately."
        )
        if tail:
            detail += f"\n\nRecent logs:\n{tail}"
        raise RuntimeError(detail)

    port = manifest.get("port")
    msg = (
        f"Plugin '{plugin_id}' launched on port {port}"
        if port
        else f"Plugin '{plugin_id}' launched"
    )
    return {"status": "ok", "message": msg, "pid": proc.pid, "port": port}


async def stop_plugin(plugin_id: str) -> dict:
    """Stop a running plugin (handles both in-memory and orphaned processes)."""
    plugin_dir = get_plugins_dir() / plugin_id
    manifest = _read_manifest(plugin_dir)

    proc = _running_processes.get(plugin_id)
    pid_from_file = _read_pid(plugin_dir)

    pid: int | None = None
    if proc is not None and proc.returncode is None:
        pid = proc.pid
    elif pid_from_file is not None and _is_pid_alive(pid_from_file):
        pid = pid_from_file

    # Fallback: PID stale but port in use (e.g. uvicorn --reload respawned worker)
    if pid is None and manifest:
        port = manifest.get("port")
        try:
            p = int(port) if port is not None else 0
            if p > 0 and _is_port_listening(p):
                pid_on_port = _get_pid_on_port(p)
                if pid_on_port is not None and (
                    _is_port_unique_to_plugin(plugin_id, p)
                    or _pid_belongs_to_plugin(pid_on_port, plugin_dir)
                ):
                    pid = pid_on_port
                elif pid_on_port is not None:
                    return {
                        "status": "ambiguous",
                        "message": (
                            f"Plugin '{plugin_id}' shares port {p} with another plugin. "
                            "Cannot safely determine which process to stop."
                        ),
                    }
        except (TypeError, ValueError):
            pass

    if pid is None:
        _running_processes.pop(plugin_id, None)
        _clear_pid(plugin_dir)
        return {
            "status": "ok",
            "message": f"Plugin '{plugin_id}' was not running",
        }

    stop_cmd = _resolve_phase_command(plugin_dir, manifest, "stop")

    if stop_cmd:
        try:
            env = _sandbox_env(plugin_dir, manifest or {})
            stop_proc = await asyncio.create_subprocess_shell(
                stop_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(plugin_dir),
                env=env,
            )
            await asyncio.wait_for(stop_proc.communicate(), timeout=10)
        except Exception:
            pass

    # Terminate the process group (or single process on Windows)
    try:
        if hasattr(os, "killpg") and hasattr(os, "getpgid"):
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError, AttributeError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    if proc is not None and proc.returncode is None:
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            pass

    if _is_pid_alive(pid):
        try:
            if hasattr(os, "killpg") and hasattr(os, "getpgid"):
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError, AttributeError):
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    _running_processes.pop(plugin_id, None)
    _clear_pid(plugin_dir)
    return {"status": "ok", "message": f"Plugin '{plugin_id}' stopped"}


# ─── Remove ──────────────────────────────────────────────────────────────


def remove_plugin(plugin_id: str) -> dict:
    """Remove a plugin directory."""
    if ".." in plugin_id or "/" in plugin_id or "\\" in plugin_id:
        raise ValueError("Invalid plugin ID")

    plugin_dir = get_plugins_dir() / plugin_id
    if not plugin_dir.is_dir():
        raise FileNotFoundError(f"Plugin '{plugin_id}' not found")

    proc = _running_processes.pop(plugin_id, None)
    if proc is not None and proc.returncode is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    pid = _read_pid(plugin_dir)
    if pid is not None and _is_pid_alive(pid):
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    shutil.rmtree(plugin_dir)
    return {"status": "ok", "message": f"Plugin '{plugin_id}' removed"}


# ─── Shell (sandboxed to plugins dir) ────────────────────────────────────


async def run_shell(command: str, cwd: str | None = None) -> dict:
    """Execute a shell command scoped to the plugins directory."""
    plugins_dir = get_plugins_dir()
    work_dir = cwd or str(plugins_dir)

    # Prevent escaping the plugins directory
    resolved = Path(work_dir).resolve()
    if not str(resolved).startswith(str(plugins_dir.resolve())):
        work_dir = str(plugins_dir)

    logger.info("Shell command: %s (cwd=%s)", command, work_dir)

    clean_env: dict[str, str] = {
        "HOME": work_dir,
        "TMPDIR": work_dir,
        "PATH": _SYSTEM_PATHS,
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
    }

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
            env=clean_env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        output = (stdout or b"").decode(errors="replace")
        if stderr:
            output += "\n" + stderr.decode(errors="replace")
        return {
            "output": output.strip()[-4000:],
            "exit_code": proc.returncode,
        }
    except TimeoutError:
        return {"output": "Command timed out (120s limit)", "exit_code": -1}
    except Exception as e:
        return {"output": f"Error: {e}", "exit_code": -1}

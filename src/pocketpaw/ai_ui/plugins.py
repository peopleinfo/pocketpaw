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
import shutil
import signal
import socket
import subprocess
import zipfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PID_FILENAME = ".pocketpaw.pid"
_LOG_FILENAME = ".pocketpaw.log"

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
PLUGINS_DIR = _PROJECT_ROOT / "plugins"

_running_processes: dict[str, asyncio.subprocess.Process] = {}

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
    venv_bin = venv_dir / "bin"
    local_bin = plugin_dir / "bin"
    path_parts = []
    if venv_bin.is_dir():
        path_parts.append(str(venv_bin))
    if local_bin.is_dir():
        path_parts.append(str(local_bin))
    path_parts.append(_SYSTEM_PATHS)

    env: dict[str, str] = {
        # Identity — everything lives in the plugin folder
        "HOME": plugin_str,
        "USER": "pocketpaw",
        "SHELL": "/bin/bash",
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
            if p > 0 and _is_port_listening(p):
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
    h = host or env.get("HOST", "0.0.0.0")
    # Use 127.0.0.1 for connect; 0.0.0.0 is bind-only
    if h in ("0.0.0.0", ""):
        h = "127.0.0.1"
    p = port if port is not None else int(env.get("PORT", "8000"))
    url = f"http://{h}:{p}/v1/chat/completions"

    payload = {
        "model": env.get("G4F_MODEL", "gpt-4o-mini"),
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": False,
    }

    try:
        import httpx

        with httpx.Client(timeout=15.0) as client:
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
        from pocketpaw.ai_ui.builtins import install_builtin

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
    install_script = dest / "install.sh"
    install_cmd = manifest.get("install")
    sandbox_env = _sandbox_install_env(dest, manifest)

    if install_script.exists():
        logger.info("Running install script for '%s'", plugin_id)
        proc = await asyncio.create_subprocess_shell(
            "bash install.sh",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(dest),
            env=sandbox_env,
        )
        await asyncio.wait_for(proc.communicate(), timeout=300)
    elif install_cmd:
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
    install_script = dest / "install.sh"
    install_cmd = manifest.get("install")
    sandbox_env = _sandbox_install_env(dest, manifest)

    if install_script.exists():
        logger.info("Running install script for '%s'", plugin_id)
        proc = await asyncio.create_subprocess_shell(
            "bash install.sh",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(dest),
            env=sandbox_env,
        )
        await asyncio.wait_for(proc.communicate(), timeout=300)
    elif install_cmd:
        logger.info(
            "Running install command for '%s': %s", plugin_id, install_cmd
        )
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

    start_cmd = manifest.get("start")
    if not start_cmd:
        raise ValueError(f"Plugin '{plugin_id}' has no start command")

    env = _sandbox_env(plugin_dir, manifest)

    logger.info(
        "Launching plugin '%s': %s (sandboxed in %s)",
        plugin_id,
        start_cmd,
        plugin_dir,
    )

    log_path = plugin_dir / _LOG_FILENAME
    log_file = log_path.open("w", encoding="utf-8")

    proc = await asyncio.create_subprocess_shell(
        start_cmd,
        stdout=log_file,
        stderr=log_file,
        cwd=str(plugin_dir),
        env=env,
        preexec_fn=os.setsid,
    )

    log_file.close()

    _running_processes[plugin_id] = proc
    _write_pid(plugin_dir, proc.pid)

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
                pid = _get_pid_on_port(p)
        except (TypeError, ValueError):
            pass

    if pid is None:
        _running_processes.pop(plugin_id, None)
        _clear_pid(plugin_dir)
        return {
            "status": "ok",
            "message": f"Plugin '{plugin_id}' was not running",
        }

    stop_cmd = manifest.get("stop") if manifest else None

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

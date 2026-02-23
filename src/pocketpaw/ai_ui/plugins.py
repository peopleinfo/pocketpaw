"""AI UI — Plugin manager.

Plugins live at plugins/<plugin-name>/ and follow a Pinokio-inspired
structure:

    plugins/
      my-app/
        pocketpaw.json      ← Required manifest
        install.sh           ← Install script (optional)
        start.sh             ← Launch script (optional)
        stop.sh              ← Stop script (optional)
        requirements.txt     ← Python deps (optional)
        package.json         ← Node deps (optional)
        ...app files...

pocketpaw.json manifest:
{
  "name": "My App",
  "description": "An AI app",
  "icon": "brain",
  "version": "1.0.0",
  "start": "start.sh",        // or "python app.py" etc
  "install": "install.sh",     // optional
  "stop": "stop.sh",           // optional
  "port": 7860,                // optional — auto-detected port
  "env": {},                   // environment variables
  "requires": ["python", "git"]
}
"""

import asyncio
import json
import logging
import os
import shutil
import signal
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Plugin directory (project root: ./plugins)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
PLUGINS_DIR = _PROJECT_ROOT / "plugins"

# Track running processes
_running_processes: dict[str, asyncio.subprocess.Process] = {}


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


def list_plugins() -> list[dict[str, Any]]:
    """List all installed plugins with their manifests and status."""
    plugins_dir = get_plugins_dir()
    plugins = []

    for item in sorted(plugins_dir.iterdir()):
        if not item.is_dir():
            continue
        manifest = _read_manifest(item)
        if manifest is None:
            # Directory without valid manifest — skip
            continue

        plugin_id = item.name
        is_running = plugin_id in _running_processes and _running_processes[plugin_id].returncode is None

        plugins.append({
            "id": plugin_id,
            "name": manifest.get("name", plugin_id),
            "description": manifest.get("description", ""),
            "icon": manifest.get("icon", "package"),
            "version": manifest.get("version", "0.0.0"),
            "port": manifest.get("port"),
            "status": "running" if is_running else "stopped",
            "path": str(item),
            "start_cmd": manifest.get("start", ""),
            "has_install": (item / "install.sh").exists() or bool(manifest.get("install")),
            "requires": manifest.get("requires", []),
            "env": manifest.get("env", {}),
            "openapi": manifest.get("openapi"),
        })

    return plugins


def get_plugin(plugin_id: str) -> dict | None:
    """Get a single plugin's details."""
    plugin_dir = get_plugins_dir() / plugin_id
    if not plugin_dir.is_dir():
        return None
    manifest = _read_manifest(plugin_dir)
    if manifest is None:
        return None

    is_running = plugin_id in _running_processes and _running_processes[plugin_id].returncode is None

    return {
        "id": plugin_id,
        "name": manifest.get("name", plugin_id),
        "description": manifest.get("description", ""),
        "icon": manifest.get("icon", "package"),
        "version": manifest.get("version", "0.0.0"),
        "port": manifest.get("port"),
        "status": "running" if is_running else "stopped",
        "path": str(plugin_dir),
        "start_cmd": manifest.get("start", ""),
        "has_install": (plugin_dir / "install.sh").exists() or bool(manifest.get("install")),
        "requires": manifest.get("requires", []),
        "env": manifest.get("env", {}),
        "readme": _read_readme(plugin_dir),
    }


def _read_readme(plugin_dir: Path) -> str | None:
    """Read README from plugin directory."""
    for name in ["README.md", "readme.md", "README.txt", "README"]:
        readme_path = plugin_dir / name
        if readme_path.exists():
            try:
                return readme_path.read_text(encoding="utf-8")[:5000]
            except OSError:
                pass
async def install_plugin(source: str) -> dict:
    """Install a plugin from a git URL or local path.

    Source can be:
      - Git URL: https://github.com/user/repo.git
      - Git shorthand: user/repo
      - Local path: /path/to/plugin
    """
    plugins_dir = get_plugins_dir()

    # Sanitize
    if ".." in source or ";" in source or "|" in source or "&" in source:
        raise ValueError("That doesn't look like a valid app URL. Try something like: user/repo")

    # Handle built-in curated plugins
    if source.startswith("builtin:"):
        app_id = source.split(":", 1)[1]
        from pocketpaw.ai_ui.builtins import install_builtin
        return await install_builtin(app_id, plugins_dir)

    # Determine if it's a local path
    src_path = Path(source).expanduser()
    if src_path.is_dir():
        # Local plugin — copy it
        manifest = _read_manifest(src_path)
        if manifest is None:
            raise ValueError(
                f"This folder is missing a pocketpaw.json config file. "
                "PocketPaw plugins need this file to know how to install and run the app."
            )
        plugin_id = src_path.name
        dest = plugins_dir / plugin_id
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src_path, dest)
        return {"status": "ok", "message": f"{manifest['name']} has been added!", "plugin_id": plugin_id}

    # Git URL
    git_url = source
    if not git_url.startswith(("http://", "https://", "git@")):
        # Shorthand: user/repo
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
            "git", "clone", "--depth=1", git_url, tmpdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr_out = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode != 0:
            err = stderr_out.decode(errors="replace").strip()
            if "not found" in err.lower() or "404" in err:
                raise RuntimeError(f"Couldn't find that app. Double-check the URL and try again.")
            raise RuntimeError(f"Couldn't download the app. Please check your internet connection and try again.")

        tmp = Path(tmpdir)
        manifest = _read_manifest(tmp)

        # Require manifest instead of auto-generating
        if manifest is None:
            raise ValueError(
                "This repository doesn't seem to be a PocketPaw plugin. "
                "It's missing the required `pocketpaw.json` file."
            )

        # Derive plugin ID from repo name
        repo_name = git_url.rstrip("/").rstrip(".git").split("/")[-1]
        plugin_id = repo_name
        dest = plugins_dir / plugin_id
        if dest.exists():
            shutil.rmtree(dest)

        # Copy everything
        shutil.copytree(tmp, dest, dirs_exist_ok=True)
        # Remove .git directory
        git_dir = dest / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)

    # Run install script if present
    install_script = dest / "install.sh"
    install_cmd = manifest.get("install")
    if install_script.exists():
        logger.info("Running install script for '%s'", plugin_id)
        proc = await asyncio.create_subprocess_shell(
            f"cd {dest} && bash install.sh",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=300)
    elif install_cmd:
        logger.info("Running install command for '%s': %s", plugin_id, install_cmd)
        proc = await asyncio.create_subprocess_shell(
            f"cd {dest} && {install_cmd}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=300)

    return {"status": "ok", "message": f"{manifest['name']} has been added!", "plugin_id": plugin_id}


async def launch_plugin(plugin_id: str) -> dict:
    """Launch a plugin's start command."""
    if plugin_id in _running_processes:
        existing = _running_processes[plugin_id]
        if existing.returncode is None:
            return {"status": "already_running", "message": f"Plugin '{plugin_id}' is already running"}

    plugin_dir = get_plugins_dir() / plugin_id
    manifest = _read_manifest(plugin_dir)
    if manifest is None:
        raise ValueError(f"Plugin '{plugin_id}' not found or missing manifest")

    start_cmd = manifest.get("start")
    if not start_cmd:
        raise ValueError(f"Plugin '{plugin_id}' has no start command")

    env = {**os.environ, **(manifest.get("env") or {})}
    port = manifest.get("port")
    if port:
        env["PORT"] = str(port)

    logger.info("Launching plugin '%s': %s (in %s)", plugin_id, start_cmd, plugin_dir)

    proc = await asyncio.create_subprocess_shell(
        f"cd {plugin_dir} && {start_cmd}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        preexec_fn=os.setsid,  # Create new process group for clean termination
    )
    _running_processes[plugin_id] = proc

    return {
        "status": "ok",
        "message": f"Plugin '{plugin_id}' launched on port {port}" if port else f"Plugin '{plugin_id}' launched",
        "pid": proc.pid,
        "port": port,
    }


async def stop_plugin(plugin_id: str) -> dict:
    """Stop a running plugin."""
    proc = _running_processes.get(plugin_id)
    if proc is None or proc.returncode is not None:
        _running_processes.pop(plugin_id, None)
        return {"status": "ok", "message": f"Plugin '{plugin_id}' was not running"}

    # Also try running stop script
    plugin_dir = get_plugins_dir() / plugin_id
    manifest = _read_manifest(plugin_dir)
    stop_cmd = manifest.get("stop") if manifest else None

    if stop_cmd:
        try:
            stop_proc = await asyncio.create_subprocess_shell(
                f"cd {plugin_dir} && {stop_cmd}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(stop_proc.communicate(), timeout=10)
        except Exception:
            pass

    # Terminate the process group
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass

    # Wait a bit, then force kill if still running
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except TimeoutError:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    _running_processes.pop(plugin_id, None)
    return {"status": "ok", "message": f"Plugin '{plugin_id}' stopped"}


def remove_plugin(plugin_id: str) -> dict:
    """Remove a plugin directory."""
    # Sanitize
    if ".." in plugin_id or "/" in plugin_id or "\\" in plugin_id:
        raise ValueError("Invalid plugin ID")

    plugin_dir = get_plugins_dir() / plugin_id
    if not plugin_dir.is_dir():
        raise FileNotFoundError(f"Plugin '{plugin_id}' not found")

    # Stop if running
    if plugin_id in _running_processes:
        proc = _running_processes[plugin_id]
        if proc.returncode is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        _running_processes.pop(plugin_id, None)

    shutil.rmtree(plugin_dir)
    return {"status": "ok", "message": f"Plugin '{plugin_id}' removed"}


async def run_shell(command: str, cwd: str | None = None) -> dict:
    """Execute a shell command and return structured output."""
    work_dir = cwd or str(get_plugins_dir())
    logger.info("Shell command: %s (cwd=%s)", command, work_dir)

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        output = (stdout or b"").decode(errors="replace")
        if stderr:
            output += "\n" + stderr.decode(errors="replace")
        return {
            "output": output.strip()[-4000:],  # Last 4KB
            "exit_code": proc.returncode,
        }
    except TimeoutError:
        return {"output": "Command timed out (120s limit)", "exit_code": -1}
    except Exception as e:
        return {"output": f"Error: {e}", "exit_code": -1}

"""Built-in app registry with auto-discovery.

Every Python module in this package (except ``_base``) that exposes a
``DEFINITION`` dict is auto-registered.  To add a new built-in, drop a
new ``.py`` file here — no other wiring needed.
"""

import importlib
import json
import logging
import os
import pkgutil
import platform
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ─── Auto-discovery ──────────────────────────────────────────────────────

_REGISTRY: dict[str, dict[str, Any]] = {}


def _discover() -> None:
    """Import every sibling module and collect its DEFINITION."""
    if _REGISTRY:
        return
    package_dir = Path(__file__).resolve().parent
    for info in pkgutil.iter_modules([str(package_dir)]):
        if info.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{__name__}.{info.name}")
            defn = getattr(mod, "DEFINITION", None)
            if defn and isinstance(defn, dict) and "id" in defn:
                _REGISTRY[defn["id"]] = defn
        except Exception:
            logger.warning("Failed to load builtin module '%s'", info.name, exc_info=True)


def get_registry() -> dict[str, dict[str, Any]]:
    """Return the full ``{id: definition}`` registry."""
    _discover()
    return dict(_REGISTRY)


def get_gallery() -> list[dict[str, Any]]:
    """Return gallery entries for all registered builtins."""
    _discover()
    return [defn["gallery"] for defn in _REGISTRY.values() if "gallery" in defn]


def get_install_block_reason(app_id: str) -> str | None:
    """Return install block reason for current host, or None when installable."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if app_id == "wan2gp" and system == "darwin":
        if machine in {"arm64", "aarch64"}:
            return "Wan2GP is unavailable on macOS arm64. Use Windows/Linux with NVIDIA GPU."
        return "Wan2GP is unavailable on macOS in one-click mode."

    return None


def _safe_rmtree(path: Path) -> None:
    """Remove a directory tree, handling read-only files on Windows.

    Git marks pack/object files as read-only, which causes ``shutil.rmtree``
    to raise ``[WinError 5] Access is denied`` on Windows.  This helper
    clears the read-only flag before retrying the removal.
    """

    def _on_error(func, fpath, exc_info):
        try:
            os.chmod(fpath, stat.S_IWRITE)
            func(fpath)
        except Exception as e:
            if str(fpath) == str(path):
                raise RuntimeError(
                    f"Failed to clear directory (files are locked). Is the plugin still running? ({e})"
                ) from e
            raise RuntimeError(f"Failed to remove {fpath}: {e}") from e

    shutil.rmtree(path, onerror=_on_error)


# ─── Install logic ───────────────────────────────────────────────────────


def get_install_steps(app_id: str) -> list[dict[str, str]]:
    """Return Pinokio-style install step descriptions for a built-in app."""
    _discover()
    defn = _REGISTRY.get(app_id)
    if not defn:
        return []
    manifest = defn.get("manifest", {})
    steps = []
    if defn.get("git_source"):
        steps.append({"id": "clone", "label": "Downloading repository"})
    elif defn.get("source_dir"):
        steps.append({"id": "copy", "label": "Copying source files"})
    py_version = manifest.get("python_version")
    if py_version:
        steps.append({"id": "python", "label": f"Setting up Python {py_version}"})
    if manifest.get("install"):
        cuda = manifest.get("cuda_version")
        if cuda:
            steps.append({"id": "install", "label": f"Installing dependencies (CUDA {cuda})"})
        else:
            steps.append({"id": "install", "label": "Installing dependencies"})
    steps.append({"id": "done", "label": "Ready to launch"})
    return steps


async def install_builtin(app_id: str, plugins_dir: Path, log_handler=None) -> dict:
    """Install a built-in app into *plugins_dir*.

    Two modes depending on the definition:
      1. **Inline files** — writes ``manifest`` + ``files`` directly.
      2. **Git source**  — clones the repo, then overlays ``manifest``
         and any extra ``files`` on top.

    When *log_handler* is provided, it is called with progress messages
    so the frontend can stream install output in real time.
    """
    import asyncio

    _discover()

    if app_id not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise ValueError(f"Unknown built-in app: {app_id}. Available: {available}")

    async def _log(msg: str) -> None:
        if log_handler:
            await log_handler(msg)
        logger.info("[builtin:%s] %s", app_id, msg)

    defn = _REGISTRY[app_id]
    dest = plugins_dir / app_id

    source_dir = defn.get("source_dir")
    git_source = defn.get("git_source")

    # --- Step: clone / copy ---
    if source_dir:
        await _log("step:copy")
        await _log("Copying source files...")
        _copy_source(Path(source_dir), dest)
        await _log("Source files copied.")
    elif git_source:
        await _log("step:clone")
        await _log(f"Cloning {git_source} ...")
        await _clone_source(git_source, dest)
        await _log("Repository cloned successfully.")
    else:
        if dest.exists():
            _safe_rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)

    # Write manifest
    (dest / "pocketpaw.json").write_text(json.dumps(defn["manifest"], indent=2), encoding="utf-8")

    # Write overlay files (install.py, start.py, openapi.json, etc.)
    for filename, content in defn.get("files", {}).items():
        (dest / filename).write_text(content, encoding="utf-8")

    # Run install command in sandboxed env (resolved cross-platform)
    from pocketpaw.ai_ui.plugins import (
        _ensure_isolated_python,
        _resolve_phase_command,
        _sandbox_install_env,
    )

    # --- Step: provision Python ---
    py_version = defn["manifest"].get("python_version")
    if py_version:
        await _log("step:python")
        await _log(f"Provisioning isolated Python {py_version} environment...")
        _ensure_isolated_python(dest, defn["manifest"])
        await _log(f"Python {py_version} environment ready.")

    # --- Step: install deps ---
    install_cmd = _resolve_phase_command(dest, defn["manifest"], "install")
    if install_cmd:
        await _log("step:install")
        await _log(f"Running: {install_cmd}")

        sandbox_env = _sandbox_install_env(dest, defn["manifest"])
        sandbox_env["PYTHONUNBUFFERED"] = "1"
        sandbox_env["PYTHONIOENCODING"] = "utf-8"

        if log_handler:
            # Stream output line-by-line for real-time UI updates
            proc = await asyncio.create_subprocess_shell(
                install_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(dest),
                env=sandbox_env,
            )
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                await log_handler(line.decode(errors="replace").rstrip("\r\n"))
            await proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(
                    f"Install failed for '{app_id}' (exit code {proc.returncode}). "
                    "Check the log output above for details."
                )
        else:
            from pocketpaw.ai_ui.plugins import _async_subprocess_shell

            proc = await _async_subprocess_shell(
                install_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(dest),
                env=sandbox_env,
            )
            if proc.returncode != 0:
                err = proc.stderr.decode(errors="replace").strip()
                if not err:
                    err = proc.stdout.decode(errors="replace").strip()
                if not err:
                    err = f"[No output] Command '{install_cmd}' exited with code {proc.returncode}."
                if err and len(err.splitlines()) > 50:
                    err = "...\n" + "\n".join(err.splitlines()[-50:])
                raise RuntimeError(f"Failed to setup built-in '{app_id}': {err}")

    await _log("step:done")
    name = defn["manifest"].get("name", app_id)
    await _log(f"{name} installed successfully!")
    return {"status": "ok", "message": f"{name} has been added!", "plugin_id": app_id}


def _copy_source(source: Path, dest: Path) -> None:
    """Copy a local source directory into *dest*, replacing any existing content."""
    if dest.exists():
        _safe_rmtree(dest)
    shutil.copytree(source, dest)


async def _clone_source(git_url: str, dest: Path) -> None:
    """Clone a git repo into *dest*, removing any existing directory first."""
    if dest.exists():
        _safe_rmtree(dest)

    from pocketpaw.ai_ui.plugins import _async_subprocess_exec

    proc = await _async_subprocess_exec(
        "git",
        "clone",
        "--depth=1",
        git_url,
        str(dest),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"Couldn't clone {git_url}. Check your internet connection.\n{err}")

    # Remove .git directory — the plugin is a snapshot, not a live repo
    git_dir = dest / ".git"
    if git_dir.exists():
        _safe_rmtree(git_dir)

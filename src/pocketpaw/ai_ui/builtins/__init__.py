"""Built-in app registry with auto-discovery.

Every Python module in this package (except ``_base``) that exposes a
``DEFINITION`` dict is auto-registered.  To add a new built-in, drop a
new ``.py`` file here — no other wiring needed.
"""

import asyncio
import importlib
import json
import logging
import pkgutil
import shutil
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


# ─── Install logic ───────────────────────────────────────────────────────

async def install_builtin(app_id: str, plugins_dir: Path) -> dict:
    """Install a built-in app into *plugins_dir*.

    Two modes depending on the definition:
      1. **Inline files** — writes ``manifest`` + ``files`` directly.
      2. **Git source**  — clones the repo, then overlays ``manifest``
         and any extra ``files`` on top.
    """
    _discover()

    if app_id not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise ValueError(f"Unknown built-in app: {app_id}. Available: {available}")

    defn = _REGISTRY[app_id]
    dest = plugins_dir / app_id

    git_source = defn.get("git_source")

    if git_source:
        await _clone_source(git_source, dest)
    else:
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)

    # Write manifest
    (dest / "pocketpaw.json").write_text(
        json.dumps(defn["manifest"], indent=2), encoding="utf-8"
    )

    # Write overlay files (install.sh, start.sh, openapi.json, etc.)
    for filename, content in defn.get("files", {}).items():
        (dest / filename).write_text(content, encoding="utf-8")

    # Run install command in sandboxed env
    install_cmd = defn["manifest"].get("install")
    if install_cmd:
        from pocketpaw.ai_ui.plugins import _sandbox_install_env

        sandbox_env = _sandbox_install_env(dest, defn["manifest"])
        proc = await asyncio.create_subprocess_shell(
            install_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(dest),
            env=sandbox_env,
        )
        _, stderr_out = await asyncio.wait_for(
            proc.communicate(), timeout=300
        )

        if proc.returncode != 0:
            err = stderr_out.decode(errors="replace").strip()
            raise RuntimeError(
                f"Failed to setup built-in '{app_id}': {err}"
            )

    name = defn["manifest"].get("name", app_id)
    return {"status": "ok", "message": f"{name} has been added!", "plugin_id": app_id}


async def _clone_source(git_url: str, dest: Path) -> None:
    """Clone a git repo into *dest*, removing any existing directory first."""
    if dest.exists():
        shutil.rmtree(dest)

    proc = await asyncio.create_subprocess_exec(
        "git", "clone", "--depth=1", git_url, str(dest),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr_out = await asyncio.wait_for(proc.communicate(), timeout=300)
    if proc.returncode != 0:
        err = stderr_out.decode(errors="replace").strip()
        raise RuntimeError(
            f"Couldn't clone {git_url}. Check your internet connection.\n{err}"
        )

    # Remove .git directory — the plugin is a snapshot, not a live repo
    git_dir = dest / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir)

"""Scaffold PocketPaw AI UI plugins from Python repos.

This module is used by the `/create-ai-ui-plugin` skill to convert a plain
Python app (GitHub repo or local folder) into a PocketPaw AI UI plugin by
creating pocketpaw.json + install/start scripts.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ScaffoldResult:
    plugin_id: str
    plugin_dir: Path
    already_plugin: bool
    copied_from: str


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower())
    slug = slug.strip("-")
    return slug or "plugin"


def _guess_plugin_id_from_source(source: str) -> str:
    src = source.rstrip("/")
    if src.endswith(".git"):
        src = src[:-4]
    name = src.split("/")[-1]
    return _slugify(name)


def _resolve_source_to_dir(source: str, tmp_root: Path) -> tuple[Path, str]:
    src_path = Path(source).expanduser()
    if src_path.is_dir():
        return src_path.resolve(), "local"

    git_url = source
    if not source.startswith(("http://", "https://", "git@")):
        parts = source.split("/")
        if len(parts) == 2:
            git_url = f"https://github.com/{source}.git"
        else:
            raise ValueError("source must be local path, owner/repo, or full git URL")

    checkout = tmp_root / "repo"
    proc = subprocess.run(
        ["git", "clone", "--depth=1", git_url, str(checkout)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "git clone failed").strip()
        raise RuntimeError(f"clone failed: {err}")
    return checkout, git_url


def _detect_entrypoint(repo_dir: Path) -> tuple[str, int]:
    app_py = repo_dir / "app.py"
    main_py = repo_dir / "main.py"
    streamlit_candidates = [repo_dir / "streamlit_app.py", repo_dir / "app.py"]

    if app_py.exists():
        text = app_py.read_text(encoding="utf-8", errors="ignore")
        if "FastAPI(" in text:
            return "python -m uvicorn app:app --host 0.0.0.0 --port \"${PORT:-8000}\"", 8000
        if "Flask(" in text:
            cmd = (
                "export FLASK_APP=app.py && flask run "
                "--host 0.0.0.0 --port \"${PORT:-8000}\""
            )
            return cmd, 8000
        if ".launch(" in text and "gradio" in text.lower():
            return "python app.py", 7860

    if main_py.exists():
        text = main_py.read_text(encoding="utf-8", errors="ignore")
        if "FastAPI(" in text:
            return "python -m uvicorn main:app --host 0.0.0.0 --port \"${PORT:-8000}\"", 8000

    for candidate in streamlit_candidates:
        if candidate.exists():
            text = candidate.read_text(encoding="utf-8", errors="ignore")
            if "streamlit" in text.lower():
                name = candidate.name
                cmd = (
                    f"streamlit run {name} --server.address 0.0.0.0 "
                    "--server.port \"${PORT:-8501}\""
                )
                return cmd, 8501

    if app_py.exists():
        return "python app.py", 8000
    if main_py.exists():
        return "python main.py", 8000

    py_files = sorted(repo_dir.glob("*.py"))
    if py_files:
        return f"python {py_files[0].name}", 8000

    raise ValueError("No Python entrypoint found (expected app.py, main.py, or similar)")


def _write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def _ensure_scaffold(plugin_dir: Path, plugin_id: str) -> None:
    start_cmd, port = _detect_entrypoint(plugin_dir)

    install_script = """#!/bin/bash
set -euo pipefail

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip

if [ -f requirements.txt ]; then
  pip install -r requirements.txt
elif [ -f pyproject.toml ]; then
  pip install .
else
  echo \"No requirements.txt or pyproject.toml found; skipping dependency install.\"
fi
"""

    start_script = f"""#!/bin/bash
set -euo pipefail

if [ -d .venv ]; then
  source .venv/bin/activate
fi

exec {start_cmd}
"""

    manifest = {
        "name": plugin_id.replace("-", " ").title(),
        "description": "Auto-generated PocketPaw AI UI plugin scaffold.",
        "icon": "box",
        "version": "0.1.0",
        "start": "bash start.sh",
        "install": "bash install.sh",
        "requires": ["python"],
        "port": port,
        "web_view": "iframe",
        "web_view_path": "/",
        "env": {"PORT": str(port)},
    }

    _write_if_missing(plugin_dir / "install.sh", install_script)
    _write_if_missing(plugin_dir / "start.sh", start_script)
    if not (plugin_dir / "pocketpaw.json").exists():
        (plugin_dir / "pocketpaw.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    for script in (plugin_dir / "install.sh", plugin_dir / "start.sh"):
        script.chmod(0o755)


def scaffold_plugin(
    source: str,
    *,
    project_root: Path,
    plugin_id: str | None = None,
    install: bool = True,
) -> ScaffoldResult:
    """Convert source into a PocketPaw plugin directory under `<project_root>/plugins`.

    If source already contains `pocketpaw.json`, it is copied as-is.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        source_dir, copied_from = _resolve_source_to_dir(source, tmp_root)

        final_id = _slugify(plugin_id or _guess_plugin_id_from_source(source))
        plugins_dir = project_root / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)
        dest = plugins_dir / final_id

        if install:
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(source_dir, dest)
        else:
            dest = source_dir

        has_manifest = (dest / "pocketpaw.json").exists()
        if not has_manifest:
            _ensure_scaffold(dest, final_id)

        return ScaffoldResult(
            plugin_id=final_id,
            plugin_dir=dest,
            already_plugin=has_manifest,
            copied_from=copied_from,
        )


def _parse_source_and_optional_id(raw_source: str) -> tuple[str, str | None]:
    parts = raw_source.split()
    if len(parts) <= 1:
        return raw_source, None
    return parts[0], parts[1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scaffold PocketPaw AI UI plugin from a Python app"
    )
    parser.add_argument(
        "--source",
        required=True,
        help="GitHub URL, owner/repo, local path, optionally followed by plugin_id",
    )
    parser.add_argument("--project-root", default=".", help="Project root containing plugins/")
    parser.add_argument("--plugin-id", default=None, help="Override plugin id")
    parser.add_argument(
        "--install",
        action="store_true",
        help="Copy into project plugins/ (default for skill use)",
    )
    args = parser.parse_args()

    source, inline_id = _parse_source_and_optional_id(args.source)
    project_root = Path(args.project_root).resolve()
    result = scaffold_plugin(
        source,
        project_root=project_root,
        plugin_id=args.plugin_id or inline_id,
        install=args.install,
    )

    print(
        json.dumps(
            {
                "status": "ok",
                "plugin_id": result.plugin_id,
                "plugin_dir": str(result.plugin_dir),
                "already_plugin": result.already_plugin,
                "copied_from": result.copied_from,
                "generated": ["pocketpaw.json", "install.sh", "start.sh"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

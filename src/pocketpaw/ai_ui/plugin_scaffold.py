"""Scaffold PocketPaw AI UI plugins from Python, Node.js, or Pinokio repos.

This module is used by the `/create-ai-ui-plugin` skill to convert a source
repository (local path / owner-repo / git URL) into a PocketPaw AI UI plugin.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass
class ScaffoldResult:
    plugin_id: str
    plugin_dir: Path
    already_plugin: bool
    copied_from: str


@dataclass
class AppDetection:
    kind: Literal["python", "node"]
    start_cmd: str
    port: int
    app_subdir: str
    source_repo: str | None
    pinokio_torch: bool
    requires_nvidia: bool


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower())
    slug = slug.strip("-")
    return slug or "plugin"


def _guess_plugin_id_from_source(source: str) -> str:
    if source.strip() in {"", ".", "./"}:
        try:
            return _slugify(Path.cwd().resolve().name)
        except Exception:
            return "plugin"

    src_path = Path(source).expanduser()
    if src_path.is_dir():
        return _slugify(src_path.resolve().name)

    src = source.rstrip("/")
    if src.endswith(".git"):
        src = src[:-4]
    name = src.split("/")[-1]
    return _slugify(name)


def _safe_rmtree(path: Path) -> None:
    def _onerror(func, p, exc_info):  # noqa: ANN001
        if isinstance(exc_info[1], FileNotFoundError):
            return
        raise exc_info[1]

    shutil.rmtree(path, onerror=_onerror)


def _normalize_project_root(project_root: Path) -> Path:
    """Accept either project root or the plugins directory itself.

    Some callers accidentally pass `<root>/plugins` as --project-root, which
    otherwise creates nested `<root>/plugins/plugins/...` directories.
    """
    resolved = project_root.resolve()
    if resolved.name == "plugins":
        return resolved.parent
    return resolved


def _copytree_ignore(
    source_root: Path, *, plugin_id: str, ignore_plugins: bool
) -> Callable[[str, list[str]], set[str]]:
    base_ignores = shutil.ignore_patterns(
        ".git",
        ".hg",
        ".svn",
        ".DS_Store",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "env",
        ".uv-cache",
        "node_modules",
        "dist",
        "build",
        "*.egg-info",
    )

    plugins_dir = (source_root / "plugins").resolve()

    def _ignore(src: str, names: list[str]) -> set[str]:
        ignored = set(base_ignores(src, names))
        try:
            src_path = Path(src).resolve()
        except Exception:
            return ignored

        if ignore_plugins and src_path == source_root.resolve() and "plugins" in names:
            ignored.add("plugins")

        if src_path == plugins_dir and plugin_id in names:
            ignored.add(plugin_id)

        return ignored

    return _ignore


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


def _extract_port(text: str, default: int) -> int:
    patterns = [
        r"--port(?:=|\s+)(\d{2,5})",
        r"--server-port(?:=|\s+)(\d{2,5})",
        r"--server\.port(?:=|\s+)(\d{2,5})",
        r"PORT(?:=|:)\s*['\"]?(\d{2,5})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                val = int(match.group(1))
                if 1 <= val <= 65535:
                    return val
            except ValueError:
                pass
    return default


def _detect_python_entrypoint(repo_dir: Path) -> tuple[str, int]:
    app_py = repo_dir / "app.py"
    main_py = repo_dir / "main.py"
    streamlit_candidates = [repo_dir / "streamlit_app.py", repo_dir / "app.py"]

    if app_py.exists():
        text = app_py.read_text(encoding="utf-8", errors="ignore")
        if "FastAPI(" in text:
            return "python -m uvicorn app:app --host 0.0.0.0 --port {PORT}", 8000
        if "Flask(" in text:
            cmd = "python -m flask --app app.py run --host 0.0.0.0 --port {PORT}"
            return cmd, 8000
        if ".launch(" in text and "gradio" in text.lower():
            return "python app.py", 7860

    if main_py.exists():
        text = main_py.read_text(encoding="utf-8", errors="ignore")
        if "FastAPI(" in text:
            return "python -m uvicorn main:app --host 0.0.0.0 --port {PORT}", 8000

    for candidate in streamlit_candidates:
        if candidate.exists():
            text = candidate.read_text(encoding="utf-8", errors="ignore")
            if "streamlit" in text.lower():
                cmd = (
                    f"streamlit run {candidate.name} --server.address 0.0.0.0 "
                    "--server.port {PORT}"
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


def _detect_node_entrypoint(repo_dir: Path) -> tuple[str, int]:
    package_json = repo_dir / "package.json"
    if package_json.exists():
        try:
            pkg = json.loads(package_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid package.json: {exc}") from exc

        scripts = pkg.get("scripts", {}) if isinstance(pkg, dict) else {}
        if "start" in scripts and isinstance(scripts["start"], str):
            return "npm run start", _extract_port(scripts["start"], 3000)
        if "dev" in scripts and isinstance(scripts["dev"], str):
            return "npm run dev", _extract_port(scripts["dev"], 3000)

    for entry in ("server.js", "index.js", "app.js"):
        if (repo_dir / entry).exists():
            return f"node {entry}", 3000

    raise ValueError(
        "No Node.js entrypoint found (expected package.json scripts or server.js/index.js)"
    )


def _extract_js_message_commands(text: str) -> list[str]:
    commands: list[str] = []
    for block in re.findall(r"message\s*:\s*\[(.*?)\]", text, flags=re.DOTALL):
        items = re.findall(r'["\']([^"\']+)["\']', block)
        commands.extend(items)
    commands.extend(re.findall(r'message\s*:\s*["\']([^"\']+)["\']', text))
    cleaned: list[str] = []
    for raw in commands:
        cmd = re.sub(r"\{\{.*?\}\}", "", raw)
        cmd = re.sub(r"\s+", " ", cmd).strip()
        if cmd:
            cleaned.append(cmd)
    return cleaned


def _extract_pinokio_clone_url(text: str) -> str | None:
    match = re.search(r"git\s+clone\s+([^\s\"']+)\s+app\b", text)
    if match:
        return match.group(1).strip()
    return None


def _looks_like_python_cmd(cmd: str) -> bool:
    lowered = cmd.lower()
    return lowered.startswith(("python ", "python3 ", "uvicorn ", "flask "))


def _looks_like_node_cmd(cmd: str) -> bool:
    lowered = cmd.lower()
    return lowered.startswith(("node ", "npm ", "pnpm ", "yarn ", "bun "))


def _detect_pinokio_repo(repo_dir: Path) -> AppDetection | None:
    pinokio_js = repo_dir / "pinokio.js"
    install_js = repo_dir / "install.js"
    start_js = repo_dir / "start.js"
    if not pinokio_js.exists() or not (install_js.exists() or start_js.exists()):
        return None

    install_text = (
        install_js.read_text(encoding="utf-8", errors="ignore") if install_js.exists() else ""
    )
    start_text = start_js.read_text(encoding="utf-8", errors="ignore") if start_js.exists() else ""

    clone_url = _extract_pinokio_clone_url(install_text)
    app_subdir = "app" if clone_url else "."
    app_root = repo_dir / app_subdir

    start_candidates = _extract_js_message_commands(start_text)
    start_cmd = ""
    for candidate in start_candidates:
        if _looks_like_python_cmd(candidate) or _looks_like_node_cmd(candidate):
            start_cmd = candidate
            break

    if not start_cmd:
        if (app_root / "package.json").exists():
            start_cmd, port = _detect_node_entrypoint(app_root)
            kind: Literal["python", "node"] = "node"
        else:
            start_cmd, port = _detect_python_entrypoint(app_root)
            kind = "python"
    elif _looks_like_node_cmd(start_cmd):
        kind = "node"
        port = _extract_port(start_cmd, 3000)
    else:
        kind = "python"
        port = _extract_port(start_cmd, 7860)

    requires_nvidia = (
        "requires an nvidia gpu" in install_text.lower()
        or "gpu === 'amd' || platform === 'darwin'" in install_text
    )

    return AppDetection(
        kind=kind,
        start_cmd=start_cmd,
        port=port,
        app_subdir=app_subdir,
        source_repo=clone_url,
        pinokio_torch=(repo_dir / "torch.js").exists(),
        requires_nvidia=requires_nvidia,
    )


def _detect_app(repo_dir: Path) -> AppDetection:
    pinokio = _detect_pinokio_repo(repo_dir)
    if pinokio is not None:
        return pinokio

    if (repo_dir / "package.json").exists():
        start_cmd, port = _detect_node_entrypoint(repo_dir)
        return AppDetection(
            kind="node",
            start_cmd=start_cmd,
            port=port,
            app_subdir=".",
            source_repo=None,
            pinokio_torch=False,
            requires_nvidia=False,
        )

    start_cmd, port = _detect_python_entrypoint(repo_dir)
    return AppDetection(
        kind="python",
        start_cmd=start_cmd,
        port=port,
        app_subdir=".",
        source_repo=None,
        pinokio_torch=False,
        requires_nvidia=False,
    )


def _render_install_wrapper(detection: AppDetection) -> str:
    config = {
        "app_kind": detection.kind,
        "app_subdir": detection.app_subdir,
        "source_repo": detection.source_repo,
        "torch_default": detection.pinokio_torch,
        "requires_nvidia": detection.requires_nvidia,
    }
    config_py = repr(config)

    return f"""\
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG = {config_py}
ROOT = Path(__file__).resolve().parent


def _run(cmd: str, *, cwd: Path) -> None:
    print("+", cmd)
    subprocess.run(cmd, cwd=str(cwd), shell=True, check=True)


def _has_cmd(name: str) -> bool:
    return shutil.which(name) is not None


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {{"1", "true", "yes", "on"}}


def _has_nvidia_gpu() -> bool:
    try:
        proc = subprocess.run(
            ["nvidia-smi"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _ensure_checkout(app_dir: Path, source_repo: str | None) -> None:
    if source_repo and not app_dir.exists():
        _run(f"git clone {{source_repo}} {{app_dir.name}}", cwd=ROOT)


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _ensure_venv(app_dir: Path) -> Path:
    venv_dir = app_dir / ".venv"
    py = _venv_python(venv_dir)
    if py.exists():
        return py
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True, cwd=str(app_dir))
    return _venv_python(venv_dir)


def _pip(py: Path, *args: str) -> None:
    # Prefer `uv pip install --python ...` when available for faster, more
    # reliable wheel resolution on heavy CUDA stacks; fall back to pip.
    if args and args[0] == "install" and _has_cmd("uv"):
        subprocess.run(["uv", "pip", "install", "--python", str(py), *args[1:]], check=True)
        return
    subprocess.run([str(py), "-m", "pip", *args], check=True)


def _python_mm(py: Path) -> tuple[int, int]:
    out = subprocess.check_output(
        [str(py), "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
        text=True,
    ).strip()
    major, minor = out.split()
    return int(major), int(minor)


def _install_pinokio_torch_profile(py: Path, *, with_xformers: bool) -> None:
    system = platform.system().lower()
    major, minor = _python_mm(py)
    if system == "windows":
        torch_args = ["install", "torch==2.7.1", "torchvision==0.22.1", "torchaudio==2.7.1"]
        if with_xformers:
            torch_args.append("xformers==0.0.30")
        torch_args.extend(
            [
                "--index-url",
                "https://download.pytorch.org/whl/cu128",
                "--force-reinstall",
                "--no-deps",
            ]
        )
        _pip(py, *torch_args)
        _pip(py, "install", "triton-windows==3.3.1.post19")
        if (major, minor) == (3, 10):
            _pip(
                py,
                "install",
                "https://github.com/woct0rdho/SageAttention/releases/download/v2.2.0-windows/"
                "sageattention-2.2.0+cu128torch2.7.1-cp310-cp310-win_amd64.whl",
            )
            _pip(
                py,
                "install",
                "https://huggingface.co/cocktailpeanut/wheels/resolve/main/"
                "flash_attn-2.8.2%2Bcu128torch2.7-cp310-cp310-win_amd64.whl",
            )
        else:
            print("Skipping Sage/Flash wheels: provided Pinokio prebuilds are Python 3.10-only.")
    elif system == "linux":
        torch_args = ["install", "torch==2.7.0", "torchvision==0.22.0", "torchaudio==2.7.0"]
        if with_xformers:
            torch_args.append("xformers==0.0.30")
        torch_args.extend(
            [
                "--index-url",
                "https://download.pytorch.org/whl/cu128",
                "--force-reinstall",
            ]
        )
        _pip(py, *torch_args)
        if (major, minor) == (3, 10):
            _pip(
                py,
                "install",
                "https://huggingface.co/MonsterMMORPG/SECourses_Premium_Flash_Attention/resolve/main/"
                "sageattention-2.1.1-cp310-cp310-linux_x86_64.whl",
            )
            _pip(
                py,
                "install",
                "https://github.com/mjun0812/flash-attention-prebuild-wheels/releases/download/"
                "v0.7.16/flash_attn-2.7.4+cu128torch2.7-cp310-cp310-linux_x86_64.whl",
            )
        else:
            print("Skipping Sage/Flash wheels: provided Pinokio prebuilds are Python 3.10-only.")
        _pip(py, "install", "numpy==2.1.2")


def _install_python(app_dir: Path, *, torch_enabled: bool) -> None:
    py = _ensure_venv(app_dir)
    _pip(py, "install", "--upgrade", "pip")

    if torch_enabled:
        with_xformers = _bool_env("PINOKIO_TORCH_XFORMERS", True)
        _install_pinokio_torch_profile(py, with_xformers=with_xformers)

    requirements = app_dir / "requirements.txt"
    pyproject = app_dir / "pyproject.toml"
    setup_py = app_dir / "setup.py"
    if requirements.exists():
        _pip(py, "install", "-r", str(requirements))
    elif pyproject.exists() or setup_py.exists():
        _pip(py, "install", ".")
    else:
        print("No Python dependency file found; skipping dependency install.")


def _install_node(app_dir: Path) -> None:
    if not (app_dir / "package.json").exists():
        raise RuntimeError(f"package.json not found in {{app_dir}}")

    if (app_dir / "pnpm-lock.yaml").exists() and _has_cmd("pnpm"):
        _run("pnpm install", cwd=app_dir)
        return
    if (app_dir / "yarn.lock").exists() and _has_cmd("yarn"):
        _run("yarn install", cwd=app_dir)
        return
    if (app_dir / "package-lock.json").exists():
        _run("npm ci", cwd=app_dir)
        return
    _run("npm install", cwd=app_dir)


def main() -> int:
    if CONFIG.get("requires_nvidia") and not _bool_env("PINOKIO_ALLOW_NO_NVIDIA", False):
        if not _has_nvidia_gpu():
            print("This Pinokio app is marked NVIDIA-only. Set PINOKIO_ALLOW_NO_NVIDIA=1 to force.")
            return 1

    app_dir = ROOT / CONFIG["app_subdir"]
    source_repo = CONFIG.get("source_repo")
    _ensure_checkout(app_dir, source_repo)

    if CONFIG["app_kind"] == "python":
        torch_default = bool(CONFIG.get("torch_default", False))
        torch_enabled = _bool_env("PINOKIO_TORCH_ENABLE", torch_default)
        _install_python(app_dir, torch_enabled=torch_enabled)
    else:
        _install_node(app_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""


def _render_start_wrapper(detection: AppDetection) -> str:
    config = {
        "app_kind": detection.kind,
        "app_subdir": detection.app_subdir,
        "source_repo": detection.source_repo,
        "start_cmd": detection.start_cmd,
        "port": detection.port,
    }
    config_py = repr(config)

    return f"""\
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

CONFIG = {config_py}
ROOT = Path(__file__).resolve().parent


def _run(cmd: str, *, cwd: Path, env: dict[str, str]) -> int:
    print("+", cmd)
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, shell=True, check=False)
    return int(proc.returncode)


def _ensure_checkout(app_dir: Path, source_repo: str | None) -> None:
    if source_repo and not app_dir.exists():
        subprocess.run(
            ["git", "clone", source_repo, app_dir.name],
            check=True,
            cwd=str(ROOT),
        )


def _venv_python(app_dir: Path) -> Path | None:
    if os.name == "nt":
        py = app_dir / ".venv" / "Scripts" / "python.exe"
    else:
        py = app_dir / ".venv" / "bin" / "python"
    return py if py.exists() else None


def main() -> int:
    app_dir = ROOT / CONFIG["app_subdir"]
    _ensure_checkout(app_dir, CONFIG.get("source_repo"))

    port = str(os.getenv("PORT") or os.getenv("SERVER_PORT") or CONFIG["port"])
    env = dict(os.environ)
    env["PORT"] = port
    env.setdefault("SERVER_PORT", port)

    cmd = str(CONFIG["start_cmd"]).replace("{{PORT}}", port)
    if CONFIG["app_kind"] == "python":
        py = _venv_python(app_dir) or Path(sys.executable)
        cmd = re.sub(r"^python3?\\b", f'"{{py}}"', cmd)
    return _run(cmd, cwd=app_dir, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
"""


def _ensure_scaffold(plugin_dir: Path, plugin_id: str) -> None:
    detection = _detect_app(plugin_dir)
    install_py = _render_install_wrapper(detection)
    start_py = _render_start_wrapper(detection)

    install_sh = """#!/bin/bash
set -euo pipefail
if command -v python3 >/dev/null 2>&1; then
  exec python3 pocketpaw_install.py
fi
exec python pocketpaw_install.py
"""

    start_sh = """#!/bin/bash
set -euo pipefail
if command -v python3 >/dev/null 2>&1; then
  exec python3 pocketpaw_start.py
fi
exec python pocketpaw_start.py
"""

    env = {
        "PORT": str(detection.port),
        "SERVER_PORT": str(detection.port),
        "PINOKIO_TORCH_ENABLE": "1" if detection.pinokio_torch else "0",
        "PINOKIO_TORCH_XFORMERS": "1",
    }
    if detection.source_repo:
        env["PINOKIO_SOURCE_REPO"] = detection.source_repo
    if detection.requires_nvidia:
        env["PINOKIO_ALLOW_NO_NVIDIA"] = "0"

    requires = ["python"]
    if detection.kind == "node":
        requires.append("node")
    if detection.source_repo:
        requires.append("git")

    manifest = {
        "name": plugin_id.replace("-", " ").title(),
        "description": (
            "Auto-generated PocketPaw AI UI plugin scaffold "
            "(Python/Node/Pinokio compatible)."
        ),
        "icon": "box",
        "version": "0.2.0",
        "start": "python pocketpaw_start.py",
        "install": "python pocketpaw_install.py",
        "requires": requires,
        "port": detection.port,
        "web_view": "iframe",
        "web_view_path": "/",
        "env": env,
    }

    (plugin_dir / "pocketpaw_install.py").write_text(install_py, encoding="utf-8")
    (plugin_dir / "pocketpaw_start.py").write_text(start_py, encoding="utf-8")
    (plugin_dir / "install.sh").write_text(install_sh, encoding="utf-8")
    (plugin_dir / "start.sh").write_text(start_sh, encoding="utf-8")
    if not (plugin_dir / "pocketpaw.json").exists():
        (plugin_dir / "pocketpaw.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    for script in (
        plugin_dir / "install.sh",
        plugin_dir / "start.sh",
        plugin_dir / "pocketpaw_install.py",
        plugin_dir / "pocketpaw_start.py",
    ):
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
    project_root = _normalize_project_root(project_root)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        source_dir, copied_from = _resolve_source_to_dir(source, tmp_root)

        final_id = _slugify(plugin_id or _guess_plugin_id_from_source(source))
        plugins_dir = project_root / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)
        dest = plugins_dir / final_id

        if install:
            source_dir_resolved = source_dir.resolve()
            dest_resolved = dest.resolve()
            source_is_dest = source_dir_resolved == dest_resolved
            dest_is_within_source = dest_resolved.is_relative_to(source_dir_resolved)

            # In-place scaffolding for an already-local plugin path:
            # avoid deleting/copying the same directory onto itself.
            if source_is_dest:
                has_manifest = (dest / "pocketpaw.json").exists()
                if not has_manifest:
                    _ensure_scaffold(dest, final_id)
                return ScaffoldResult(
                    plugin_id=final_id,
                    plugin_dir=dest,
                    already_plugin=has_manifest,
                    copied_from=copied_from,
                )

            if dest.exists():
                _safe_rmtree(dest)

            ignore = _copytree_ignore(
                source_dir,
                plugin_id=final_id,
                ignore_plugins=dest_is_within_source,
            )

            copy_source = source_dir
            if dest_is_within_source:
                staged = tmp_root / "staged"
                shutil.copytree(source_dir, staged, ignore=ignore)
                copy_source = staged

            shutil.copytree(copy_source, dest, ignore=ignore)
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
        description="Scaffold PocketPaw AI UI plugin from Python/Node/Pinokio app repos"
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Git URL, owner/repo, local path, optionally followed by plugin_id",
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
                "generated": [
                    "pocketpaw.json",
                    "pocketpaw_install.py",
                    "pocketpaw_start.py",
                    "install.sh",
                    "start.sh",
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

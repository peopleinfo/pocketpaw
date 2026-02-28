"""Built-in: Wan2GP (WanGP) from deepbeepmeep/Wan2GP."""

from pocketpaw.ai_ui.builtins._base import BuiltinDefinition

_MANIFEST = {
    "name": "Wan2GP",
    "description": (
        "WanGP local UI for text/image-to-video workflows. "
        "Windows-first built-in integration for PocketPaw."
    ),
    "icon": "film",
    "version": "1.0.0",
    "start": "python pocketpaw_start.py",
    "install": "python pocketpaw_install.py",
    "requires": ["python", "git"],
    "port": 7860,
    "web_view": "iframe",
    "web_view_path": "/",
    "env": {
        "PORT": "7860",
        "SERVER_PORT": "7860",
    },
}

_INSTALL_PY = """\
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"

_SAGE_WIN = (
    "https://github.com/woct0rdho/SageAttention/releases/download/"
    "v2.2.0-windows/sageattention-2.2.0+cu128torch2.7.1-"
    "cp310-cp310-win_amd64.whl"
)
_FLASH_WIN = (
    "https://huggingface.co/cocktailpeanut/wheels/resolve/main/"
    "flash_attn-2.8.2%2Bcu128torch2.7-cp310-cp310-win_amd64.whl"
)
_SAGE_LINUX = (
    "https://huggingface.co/MonsterMMORPG/SECourses_Premium_Flash_Attention/"
    "resolve/main/sageattention-2.1.1-cp310-cp310-linux_x86_64.whl"
)
_FLASH_LINUX = (
    "https://github.com/mjun0812/flash-attention-prebuild-wheels/releases/"
    "download/v0.7.16/flash_attn-2.7.4+cu128torch2.7-cp310-cp310-linux_x86_64.whl"
)


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=str(ROOT), check=True)


def _has_uv() -> bool:
    try:
        proc = subprocess.run(
            ["uv", "--version"],
            cwd=str(ROOT),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _pip(py: Path, *args: str) -> None:
    if args and args[0] == "install" and _has_uv():
        _run(["uv", "pip", "install", "--python", str(py), *args[1:]])
        return
    _run([str(py), "-m", "pip", *args])


def _python_mm(py: Path) -> tuple[int, int]:
    out = subprocess.check_output(
        [str(py), "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
        cwd=str(ROOT),
        text=True,
    ).strip()
    major, minor = out.split()
    return int(major), int(minor)


def _ensure_venv() -> Path:
    py = _venv_python()
    if py.exists():
        return py
    _run([sys.executable, "-m", "venv", str(VENV_DIR)])
    return _venv_python()


def _has_nvidia_gpu() -> bool:
    try:
        proc = subprocess.run(
            ["nvidia-smi"],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _install_pinokio_torch_stack(py: Path) -> None:
    system = platform.system().lower()
    major, minor = _python_mm(py)

    if system == "windows":
        _pip(
            py,
            "install",
            "torch==2.7.1",
            "torchvision==0.22.1",
            "torchaudio==2.7.1",
            "xformers==0.0.30",
            "--index-url",
            "https://download.pytorch.org/whl/cu128",
            "--force-reinstall",
            "--no-deps",
        )
        _pip(py, "install", "triton-windows==3.3.1.post19")
        if (major, minor) == (3, 10):
            _pip(py, "install", _SAGE_WIN)
            _pip(py, "install", _FLASH_WIN)
        else:
            print("Skipping Sage/Flash prebuilt wheels: they are pinned to Python 3.10.")
        return

    if system == "linux":
        _pip(
            py,
            "install",
            "torch==2.7.0",
            "torchvision==0.22.0",
            "torchaudio==2.7.0",
            "xformers==0.0.30",
            "--index-url",
            "https://download.pytorch.org/whl/cu128",
            "--force-reinstall",
        )
        if (major, minor) == (3, 10):
            _pip(py, "install", _SAGE_LINUX)
            _pip(py, "install", _FLASH_LINUX)
        else:
            print("Skipping Sage/Flash prebuilt wheels: they are pinned to Python 3.10.")
        _pip(py, "install", "numpy==2.1.2")
        return

    print(f"No Pinokio torch profile for platform={system}.")


def main() -> int:
    system = platform.system().lower()
    print("Wan2GP PocketPaw install bootstrap")
    print(f"Platform: {system}")

    if system == "darwin":
        print("Detected macOS. Skipping heavy install during add.")
        print("Wan2GP start will auto-enable optional macOS mode.")
        return 0

    if not _has_nvidia_gpu() and os.getenv("WAN2GP_ALLOW_NO_NVIDIA", "0") != "1":
        print("Wan2GP requires an NVIDIA GPU for this preset install flow.")
        print("Set WAN2GP_ALLOW_NO_NVIDIA=1 to force install anyway.")
        return 1

    py = _ensure_venv()
    _pip(py, "install", "--upgrade", "pip")

    if os.getenv("WAN2GP_SKIP_PINOKIO_TORCH", "0") != "1":
        _install_pinokio_torch_stack(py)

    auto_install = os.getenv("WAN2GP_AUTO_INSTALL", "0") == "1"
    if auto_install:
        _pip(py, "install", "-r", "requirements.txt")
    else:
        print("Skipping heavy requirements in install phase.")
        print("Set WAN2GP_AUTO_INSTALL=1 to install during plugin add.")
        print("Dependencies will auto-bootstrap at first start if needed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""

_START_PY = """\
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"

_SAGE_WIN = (
    "https://github.com/woct0rdho/SageAttention/releases/download/"
    "v2.2.0-windows/sageattention-2.2.0+cu128torch2.7.1-"
    "cp310-cp310-win_amd64.whl"
)
_FLASH_WIN = (
    "https://huggingface.co/cocktailpeanut/wheels/resolve/main/"
    "flash_attn-2.8.2%2Bcu128torch2.7-cp310-cp310-win_amd64.whl"
)
_SAGE_LINUX = (
    "https://huggingface.co/MonsterMMORPG/SECourses_Premium_Flash_Attention/"
    "resolve/main/sageattention-2.1.1-cp310-cp310-linux_x86_64.whl"
)
_FLASH_LINUX = (
    "https://github.com/mjun0812/flash-attention-prebuild-wheels/releases/"
    "download/v0.7.16/flash_attn-2.7.4+cu128torch2.7-cp310-cp310-linux_x86_64.whl"
)


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=str(ROOT), check=True)


def _has_uv() -> bool:
    try:
        proc = subprocess.run(
            ["uv", "--version"],
            cwd=str(ROOT),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _pip(py: Path, *args: str) -> None:
    if args and args[0] == "install" and _has_uv():
        _run(["uv", "pip", "install", "--python", str(py), *args[1:]])
        return
    _run([str(py), "-m", "pip", *args])


def _python_mm(py: Path) -> tuple[int, int]:
    out = subprocess.check_output(
        [str(py), "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
        cwd=str(ROOT),
        text=True,
    ).strip()
    major, minor = out.split()
    return int(major), int(minor)


def _ensure_venv() -> Path:
    py = _venv_python()
    if py.exists():
        return py
    _run([sys.executable, "-m", "venv", str(VENV_DIR)])
    return _venv_python()


def _deps_ready(py: Path) -> bool:
    check = subprocess.run(
        [str(py), "-c", "import gradio, mmgp"],
        cwd=str(ROOT),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return check.returncode == 0


def _macos_requirements_file() -> Path:
    source = ROOT / "requirements.txt"
    target = ROOT / "requirements.macos.txt"
    if not source.exists():
        return source

    lines = source.read_text(encoding="utf-8").splitlines()
    filtered: list[str] = []
    has_onnxruntime_cpu = False

    for raw in lines:
        line = raw.strip()
        lower = line.lower()

        if line.startswith("--extra-index-url"):
            # CUDA nightly index is not useful on macOS and can slow resolution.
            continue
        if lower.startswith("onnxruntime-gpu"):
            continue
        if lower.startswith("rembg[gpu]"):
            filtered.append("rembg==2.0.65")
            continue
        if lower.startswith("nvidia-ml-py"):
            continue
        if lower.startswith("onnxruntime==") or lower.startswith("onnxruntime>="):
            has_onnxruntime_cpu = True
        filtered.append(raw)

    if not has_onnxruntime_cpu:
        filtered.append("onnxruntime>=1.18.0")

    target.write_text("\\n".join(filtered).rstrip() + "\\n", encoding="utf-8")
    return target


def _macos_preflight(py: Path) -> tuple[bool, str]:
    major, minor = _python_mm(py)
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return (
            False,
            "decord does not provide macOS arm64 wheels required by Wan2GP.",
        )
    if (major, minor) > (3, 8):
        return (
            False,
            "decord macOS wheels are only published up to Python 3.8 (x86_64).",
        )
    return True, ""


def _install_pinokio_torch_stack(py: Path) -> None:
    system = platform.system().lower()
    major, minor = _python_mm(py)

    if system == "windows":
        _pip(
            py,
            "install",
            "torch==2.7.1",
            "torchvision==0.22.1",
            "torchaudio==2.7.1",
            "xformers==0.0.30",
            "--index-url",
            "https://download.pytorch.org/whl/cu128",
            "--force-reinstall",
            "--no-deps",
        )
        _pip(py, "install", "triton-windows==3.3.1.post19")
        if (major, minor) == (3, 10):
            _pip(py, "install", _SAGE_WIN)
            _pip(py, "install", _FLASH_WIN)
        else:
            print("Skipping Sage/Flash prebuilt wheels: they are pinned to Python 3.10.")
        return

    if system == "linux":
        _pip(
            py,
            "install",
            "torch==2.7.0",
            "torchvision==0.22.0",
            "torchaudio==2.7.0",
            "xformers==0.0.30",
            "--index-url",
            "https://download.pytorch.org/whl/cu128",
            "--force-reinstall",
        )
        if (major, minor) == (3, 10):
            _pip(py, "install", _SAGE_LINUX)
            _pip(py, "install", _FLASH_LINUX)
        else:
            print("Skipping Sage/Flash prebuilt wheels: they are pinned to Python 3.10.")
        _pip(py, "install", "numpy==2.1.2")


def _bootstrap_deps(py: Path) -> None:
    if os.getenv("WAN2GP_SKIP_BOOTSTRAP", "0") == "1":
        print("Skipping dependency bootstrap (WAN2GP_SKIP_BOOTSTRAP=1).")
        return
    if _deps_ready(py):
        return
    print("Installing Wan2GP dependencies (first run)...")
    _pip(py, "install", "--upgrade", "pip")
    if os.getenv("WAN2GP_SKIP_PINOKIO_TORCH", "0") != "1":
        _install_pinokio_torch_stack(py)
    req_file = ROOT / "requirements.txt"
    if platform.system().lower() == "darwin":
        req_file = _macos_requirements_file()
        print(f"Using macOS compatibility requirements: {req_file.name}")
    _pip(py, "install", "-r", str(req_file.name))


def main() -> int:
    system = platform.system().lower()
    if system == "darwin" and os.getenv("WAN2GP_ALLOW_MAC") is None:
        os.environ["WAN2GP_ALLOW_MAC"] = "1"
        print("Detected macOS; enabling optional WAN2GP_ALLOW_MAC=1 automatically.")
        print("Wan2GP is Windows-first, so macOS is best-effort support.")

    py = _ensure_venv()
    if system == "darwin":
        ok, reason = _macos_preflight(py)
        if not ok:
            print("Wan2GP macOS preflight failed.")
            print(reason)
            print("Recommended: run Wan2GP on Windows/Linux with NVIDIA GPU.")
            print("Advanced: Intel macOS + Python 3.8 + manual decord build/setup.")
            return 1

    _bootstrap_deps(py)

    port = os.getenv("PORT") or os.getenv("SERVER_PORT") or "7860"
    cmd = [str(py), "wgp.py", "--listen", "--server-port", str(port)]
    print("+", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT), check=False)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
"""

DEFINITION: BuiltinDefinition = {
    "id": "wan2gp",
    "manifest": _MANIFEST,
    "git_source": "https://github.com/deepbeepmeep/Wan2GP",
    "files": {
        "pocketpaw_install.py": _INSTALL_PY,
        "pocketpaw_start.py": _START_PY,
    },
    "gallery": {
        "id": "wan2gp",
        "name": "Wan2GP",
        "description": (
            "WanGP as a PocketPaw built-in plugin. "
            "Windows-first integration with non-interactive bootstrap."
        ),
        "icon": "film",
        "source": "builtin:wan2gp",
        "stars": "Windows-first",
        "category": "Curated / Built-in",
    },
}

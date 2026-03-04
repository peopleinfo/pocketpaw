"""AI UI — GPU detection and torch profile matching.

Runs once per process and caches the result.  All output is exposed as
plain strings so install scripts can read them from environment variables.

No external dependencies beyond the stdlib: uses nvidia-smi, subprocess,
and platform only.
"""

from __future__ import annotations

import logging
import platform
import re
import subprocess
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

GpuVendor = Literal["nvidia", "amd", "apple", "none"]

# ─── CUDA wheel index map (single source of truth) ──────────────────────

_CUDA_INDEX_MAP: dict[str, str] = {
    "11.8": "https://download.pytorch.org/whl/cu118",
    "12.1": "https://download.pytorch.org/whl/cu121",
    "12.4": "https://download.pytorch.org/whl/cu124",
    "12.8": "https://download.pytorch.org/whl/cu128",
}


# ─── GpuInfo dataclass ──────────────────────────────────────────────────


@dataclass
class GpuInfo:
    """Detected GPU information."""

    vendor: GpuVendor = "none"
    model: str = ""
    vram_mb: int = 0
    cuda_version: str = ""  # e.g. "13.1" — empty if no CUDA
    torch_index_url: str = ""  # e.g. "https://download.pytorch.org/whl/cu128"

    @property
    def has_cuda(self) -> bool:
        return bool(self.cuda_version)

    def as_env(self) -> dict[str, str]:
        """Return ``POCKETPAW_GPU_*`` env vars for sandbox injection."""
        return {
            "POCKETPAW_GPU_VENDOR": self.vendor,
            "POCKETPAW_GPU_MODEL": self.model,
            "POCKETPAW_GPU_VRAM_MB": str(self.vram_mb),
            "POCKETPAW_CUDA_VERSION": self.cuda_version,
            "POCKETPAW_TORCH_INDEX_URL": self.torch_index_url,
        }

    def as_dict(self) -> dict:
        """Serialisable dict for the REST endpoint."""
        return {
            "vendor": self.vendor,
            "model": self.model,
            "vram_mb": self.vram_mb,
            "cuda_version": self.cuda_version,
            "torch_index_url": self.torch_index_url,
            "has_cuda": self.has_cuda,
        }


# ─── Torch index resolution ─────────────────────────────────────────────


def _ver_tuple(version: str) -> tuple[int, ...]:
    """Parse ``"12.8"`` → ``(12, 8)``."""
    try:
        return tuple(int(x) for x in version.split(".")[:2])
    except (ValueError, AttributeError):
        return (0, 0)


def _resolve_torch_index_url(cuda_version: str) -> str:
    """Return the nearest supported PyTorch wheel index for *cuda_version*.

    Picks the highest key in ``_CUDA_INDEX_MAP`` that is ≤ *cuda_version*.
    E.g. ``"13.1"`` → ``cu128``, ``"12.0"`` → ``cu118``.
    """
    if not cuda_version:
        return ""
    detected = _ver_tuple(cuda_version)
    best_key = ""
    best_ver: tuple[int, ...] = (0, 0)
    for key in _CUDA_INDEX_MAP:
        kver = _ver_tuple(key)
        if kver <= detected and kver >= best_ver:
            best_ver = kver
            best_key = key
    return _CUDA_INDEX_MAP.get(best_key, "")


def get_cuda_index_url(cuda_version: str | None) -> str | None:
    """Backward-compat wrapper used by ``plugins.py``."""
    return _resolve_torch_index_url(cuda_version or "") or None


# ─── Detection helpers ───────────────────────────────────────────────────


def _try_nvidia() -> GpuInfo | None:
    """Detect NVIDIA GPU via ``nvidia-smi``."""
    try:
        # Parse CUDA driver version from plain nvidia-smi header
        plain = subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if plain.returncode != 0:
            return None

        cuda_ver = ""
        for line in plain.stdout.splitlines():
            m = re.search(r"CUDA Version:\s*(\d+\.\d+)", line)
            if m:
                cuda_ver = m.group(1)
                break

        # Query GPU name + VRAM
        query = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        model = ""
        vram_mb = 0
        if query.returncode == 0 and query.stdout.strip():
            first_line = query.stdout.strip().splitlines()[0]
            if "," in first_line:
                parts = first_line.split(",", 1)
                model = parts[0].strip()
                try:
                    vram_mb = int(float(parts[1].strip()))
                except (ValueError, IndexError):
                    pass

        return GpuInfo(
            vendor="nvidia",
            model=model,
            vram_mb=vram_mb,
            cuda_version=cuda_ver,
            torch_index_url=_resolve_torch_index_url(cuda_ver),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    except Exception:
        logger.debug("Unexpected error in nvidia-smi detection", exc_info=True)
        return None


def _try_amd() -> GpuInfo | None:
    """Detect AMD GPU via ``rocm-smi`` (Linux) or ``wmic`` (Windows)."""
    # Linux: rocm-smi
    try:
        result = subprocess.run(
            ["rocm-smi", "--showproductname"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = [ln.strip() for ln in result.stdout.strip().splitlines() if ln.strip()]
            model = lines[-1] if lines else "AMD GPU"
            return GpuInfo(vendor="amd", model=model)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    # Windows: wmic
    if platform.system() == "Windows":
        try:
            result = subprocess.run(
                "wmic path win32_VideoController get name",
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    lower = line.lower()
                    if "amd" in lower or "radeon" in lower:
                        return GpuInfo(vendor="amd", model=line.strip())
        except (subprocess.TimeoutExpired, OSError):
            pass

    return None


# ─── Public API ──────────────────────────────────────────────────────────

_cached: GpuInfo | None = None
_detected: bool = False


def detect_gpu() -> GpuInfo:
    """Detect GPU information.  Cached after the first call."""
    global _cached, _detected  # noqa: PLW0603
    if _detected:
        return _cached or GpuInfo()

    _detected = True
    _cached = _do_detect()
    logger.info(
        "GPU detected: vendor=%s model=%s vram=%sMB cuda=%s torch_index=%s",
        _cached.vendor,
        _cached.model,
        _cached.vram_mb,
        _cached.cuda_version,
        _cached.torch_index_url,
    )
    return _cached


def _do_detect() -> GpuInfo:
    """Run detection probes in priority order."""
    # NVIDIA first (most common for AI workloads)
    info = _try_nvidia()
    if info:
        return info

    # AMD second
    info = _try_amd()
    if info:
        return info

    # Apple Silicon
    if platform.system() == "Darwin" and platform.machine().lower() in (
        "arm64",
        "aarch64",
    ):
        return GpuInfo(vendor="apple", model="Apple Silicon")

    return GpuInfo(vendor="none")

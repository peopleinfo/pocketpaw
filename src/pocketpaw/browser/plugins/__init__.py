# Browser plugin base — defines the interface for browser plugins within Crawlee.
"""Browser plugin abstractions for anti-detect browser system.

Plugins are browser engines that integrate with Crawlee's BrowserPool.
The default is Playwright (Chromium); Camoufox provides stealth Firefox.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PluginInfo:
    """Metadata about a browser plugin."""

    id: str  # "playwright" | "camoufox"
    name: str  # "Playwright (Chromium)"
    description: str
    icon: str = "chrome"  # Lucide icon name
    installed: bool = True
    requires_package: str | None = None  # pip package needed


# ── Plugin Registry ──────────────────────────────────────────────

_PLUGINS: dict[str, PluginInfo] = {}


def register_plugin(info: PluginInfo) -> None:
    """Register a browser plugin."""
    _PLUGINS[info.id] = info
    logger.debug("Registered browser plugin: %s", info.id)


def get_plugin(plugin_id: str) -> PluginInfo | None:
    """Get plugin info by ID."""
    return _PLUGINS.get(plugin_id)


def list_plugins() -> list[PluginInfo]:
    """Return all registered plugins."""
    return list(_PLUGINS.values())


def _check_installed(package: str) -> bool:
    """Check if a Python package is importable."""
    try:
        __import__(package)
        return True
    except ImportError:
        return False


# ── Auto-register built-in plugins ───────────────────────────────

register_plugin(
    PluginInfo(
        id="playwright",
        name="Playwright (Chromium)",
        description="Default browser engine. Fast Chromium-based with fingerprint spoofing via Crawlee.",
        icon="chrome",
        installed=True,  # playwright is a project dependency
    )
)

register_plugin(
    PluginInfo(
        id="camoufox",
        name="Camoufox (Stealth Firefox)",
        description="Custom Firefox build with C++-level fingerprint spoofing. Harder to detect.",
        icon="shield",
        installed=_check_installed("camoufox"),
        requires_package="camoufox",
    )
)


__all__ = ["PluginInfo", "register_plugin", "get_plugin", "list_plugins"]

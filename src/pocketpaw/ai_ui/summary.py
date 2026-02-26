"""Helpers for summarizing AI UI plugins for chat responses."""

from __future__ import annotations

from typing import Any


def format_plugins_summary(plugins: list[dict[str, Any]]) -> str:
    """Render installed AI UI plugins as a compact markdown summary."""
    if not plugins:
        return (
            "No AI UI plugins installed. "
            "Open AI UI at `#/ai-ui/plugins` to install one."
        )

    lines = [f"AI UI plugins ({len(plugins)}):"]
    for item in plugins:
        plugin_id = item.get("id", "unknown")
        name = item.get("name") or plugin_id
        status = item.get("status", "unknown")
        port = item.get("port")
        port_text = f", port {port}" if port else ""
        lines.append(f"- `{plugin_id}` — {name} ({status}{port_text})")

    lines.append("Tip: Open `#/ai-ui/plugins` to manage and launch plugins.")
    return "\n".join(lines)


def format_plugins_overview(
    installed: list[dict[str, Any]],
    available: list[dict[str, Any]],
) -> str:
    """Render an installed + discoverable AI UI plugin overview."""
    if not installed and not available:
        return (
            "No AI UI plugins found. "
            "Open AI UI at `#/ai-ui/plugins` or `#/ai-ui/discover` to add one."
        )

    lines = ["AI UI plugins overview:"]

    lines.append(f"Installed ({len(installed)}):")
    if installed:
        for item in installed:
            plugin_id = item.get("id", "unknown")
            name = item.get("name") or plugin_id
            status = item.get("status", "unknown")
            port = item.get("port")
            port_text = f", port {port}" if port else ""
            lines.append(f"- `{plugin_id}` — {name} ({status}{port_text})")
    else:
        lines.append("- (none)")

    lines.append(f"Available in Discover ({len(available)}):")
    if available:
        for item in available:
            plugin_id = item.get("id", "unknown")
            name = item.get("name") or plugin_id
            category = item.get("category")
            category_text = f" [{category}]" if category else ""
            lines.append(f"- `{plugin_id}` — {name}{category_text}")
    else:
        lines.append("- (none)")

    lines.append("Tips: `#/ai-ui/plugins` manages installed. `#/ai-ui/discover` installs new ones.")
    return "\n".join(lines)


def get_plugins_summary() -> str:
    """Return a summary string for installed and discoverable AI UI plugins."""
    from pocketpaw.ai_ui.builtins import get_gallery
    from pocketpaw.ai_ui.plugins import list_plugins

    installed = list_plugins()
    installed_ids = {str(item.get("id", "")) for item in installed}
    gallery = get_gallery()
    available = [item for item in gallery if str(item.get("id", "")) not in installed_ids]
    return format_plugins_overview(installed, available)

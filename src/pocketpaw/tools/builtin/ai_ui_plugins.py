"""AI UI plugin management tool for agent use."""

from __future__ import annotations

import json
from typing import Any

from pocketpaw.tools.protocol import BaseTool


class AIUIPluginsTool(BaseTool):
    """Inspect installed AI UI plugins."""

    @property
    def name(self) -> str:
        return "ai_ui_plugins"

    @property
    def description(self) -> str:
        return (
            "List AI UI plugins (installed and discoverable) or inspect one plugin by id. "
            "Useful when users ask what plugins are available."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "list_installed", "list_discover", "get"],
                    "description": "Operation to run (default: list)",
                },
                "plugin_id": {
                    "type": "string",
                    "description": "Plugin id for action='get'",
                },
            },
            "required": [],
        }

    async def execute(self, **params: Any) -> str:
        from pocketpaw.ai_ui.builtins import get_gallery
        from pocketpaw.ai_ui.plugins import get_plugin, list_plugins

        action = str(params.get("action", "list")).strip().lower() or "list"
        if action == "list":
            installed = list_plugins()
            installed_ids = {str(p.get("id", "")) for p in installed}
            discover = [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "category": p.get("category"),
                    "source": p.get("source"),
                }
                for p in get_gallery()
                if str(p.get("id", "")) not in installed_ids
            ]
            slim = [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "status": p.get("status"),
                    "port": p.get("port"),
                    "version": p.get("version"),
                }
                for p in installed
            ]
            return json.dumps(
                {
                    "installed_count": len(slim),
                    "discover_count": len(discover),
                    "installed": slim,
                    "discover": discover,
                },
                indent=2,
            )

        if action == "list_installed":
            plugins = list_plugins()
            slim = [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "status": p.get("status"),
                    "port": p.get("port"),
                    "version": p.get("version"),
                }
                for p in plugins
            ]
            return json.dumps({"count": len(slim), "plugins": slim}, indent=2)

        if action == "list_discover":
            discover = [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "category": p.get("category"),
                    "source": p.get("source"),
                }
                for p in get_gallery()
            ]
            return json.dumps({"count": len(discover), "plugins": discover}, indent=2)

        if action == "get":
            plugin_id = str(params.get("plugin_id", "")).strip()
            if not plugin_id:
                return self._error("plugin_id is required for action='get'")
            plugin = get_plugin(plugin_id)
            if plugin is None:
                return self._error(f"Plugin '{plugin_id}' not found")
            return json.dumps(plugin, indent=2)

        return self._error(
            "Unknown action. Use 'list', 'list_installed', 'list_discover', or 'get'."
        )


__all__ = ["AIUIPluginsTool"]

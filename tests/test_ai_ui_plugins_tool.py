import json
from unittest.mock import patch

import pytest

from pocketpaw.tools.builtin.ai_ui_plugins import AIUIPluginsTool


@pytest.mark.asyncio
async def test_ai_ui_plugins_tool_list():
    tool = AIUIPluginsTool()
    with patch("pocketpaw.ai_ui.plugins.list_plugins") as mock_list, patch(
        "pocketpaw.ai_ui.builtins.get_gallery"
    ) as mock_gallery:
        mock_list.return_value = [
            {
                "id": "demo",
                "name": "Demo",
                "status": "running",
                "port": 8000,
                "version": "1.0.0",
            }
        ]
        mock_gallery.return_value = [
            {"id": "demo", "name": "Demo"},
            {"id": "counter-template", "name": "Counter App (Template)", "category": "Template"},
        ]
        out = await tool.execute(action="list")
    data = json.loads(out)
    assert data["installed_count"] == 1
    assert data["discover_count"] == 1
    assert data["installed"][0]["id"] == "demo"
    assert data["discover"][0]["id"] == "counter-template"


@pytest.mark.asyncio
async def test_ai_ui_plugins_tool_list_discover():
    tool = AIUIPluginsTool()
    with patch("pocketpaw.ai_ui.builtins.get_gallery") as mock_gallery:
        mock_gallery.return_value = [{"id": "counter-template", "name": "Counter App (Template)"}]
        out = await tool.execute(action="list_discover")
    data = json.loads(out)
    assert data["count"] == 1
    assert data["plugins"][0]["id"] == "counter-template"


@pytest.mark.asyncio
async def test_ai_ui_plugins_tool_get_missing_id():
    tool = AIUIPluginsTool()
    out = await tool.execute(action="get")
    assert "plugin_id is required" in out.lower()

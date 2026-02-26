from unittest.mock import patch

from pocketpaw.ai_ui.summary import (
    format_plugins_overview,
    format_plugins_summary,
    get_plugins_summary,
)


def test_format_plugins_summary_empty():
    text = format_plugins_summary([])
    assert "No AI UI plugins installed" in text


def test_format_plugins_summary_with_items():
    plugins = [
        {
            "id": "counter-template",
            "name": "Counter App",
            "status": "stopped",
            "port": 8000,
        }
    ]
    text = format_plugins_summary(plugins)
    assert "AI UI plugins (1):" in text
    assert "counter-template" in text
    assert "Counter App" in text


def test_format_plugins_overview_sections():
    installed = [
        {"id": "demo", "name": "Demo", "status": "running", "port": 8000},
    ]
    available = [
        {"id": "counter-template", "name": "Counter App (Template)", "category": "Template"},
    ]
    text = format_plugins_overview(installed, available)
    assert "Installed (1):" in text
    assert "Available in Discover (1):" in text
    assert "counter-template" in text


def test_get_plugins_summary_includes_discover():
    with patch("pocketpaw.ai_ui.plugins.list_plugins") as mock_list, patch(
        "pocketpaw.ai_ui.builtins.get_gallery"
    ) as mock_gallery:
        mock_list.return_value = [{"id": "ai-fast-api", "name": "AI Fast API", "status": "running"}]
        mock_gallery.return_value = [
            {"id": "ai-fast-api", "name": "AI Fast API", "category": "Curated"},
            {"id": "counter-template", "name": "Counter App (Template)", "category": "Template"},
        ]
        text = get_plugins_summary()
    assert "Installed (1):" in text
    assert "Available in Discover (1):" in text
    assert "counter-template" in text

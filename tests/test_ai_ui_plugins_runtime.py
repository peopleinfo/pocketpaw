import json
import os
from unittest.mock import patch

import pytest

from pocketpaw.ai_ui import plugins


def _write_manifest(path, port: int) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "pocketpaw.json").write_text(
        json.dumps(
            {
                "name": path.name,
                "start": "echo start",
                "port": port,
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _clear_running_processes():
    plugins._running_processes.clear()
    yield
    plugins._running_processes.clear()


def test_is_plugin_running_ignores_shared_port_fallback(tmp_path):
    plugin_dir = tmp_path / "counter-template"
    _write_manifest(plugin_dir, 8000)

    with patch("pocketpaw.ai_ui.plugins.get_plugins_dir", return_value=tmp_path), patch(
        "pocketpaw.ai_ui.plugins._read_pid", return_value=None
    ), patch("pocketpaw.ai_ui.plugins._is_port_listening", return_value=True), patch(
        "pocketpaw.ai_ui.plugins._is_port_unique_to_plugin", return_value=False
    ):
        assert plugins._is_plugin_running("counter-template", plugin_dir) is False


@pytest.mark.asyncio
async def test_stop_plugin_shared_port_returns_ambiguous(tmp_path):
    plugin_a = tmp_path / "counter-template"
    plugin_b = tmp_path / "ai-fast-api"
    _write_manifest(plugin_a, 8000)
    _write_manifest(plugin_b, 8000)

    with patch("pocketpaw.ai_ui.plugins.get_plugins_dir", return_value=tmp_path), patch(
        "pocketpaw.ai_ui.plugins._read_pid", return_value=None
    ), patch("pocketpaw.ai_ui.plugins._is_port_listening", return_value=True), patch(
        "pocketpaw.ai_ui.plugins._get_pid_on_port"
    ) as mock_pid_on_port, patch("os.kill") as mock_kill:
        result = await plugins.stop_plugin("counter-template")

    assert result["status"] == "ambiguous"
    assert "shares port 8000" in result["message"]
    mock_pid_on_port.assert_not_called()
    mock_kill.assert_not_called()


def test_sandbox_env_windows_prefers_scripts_dir(tmp_path):
    plugin_dir = tmp_path / "demo"
    (plugin_dir / ".venv" / "Scripts").mkdir(parents=True)
    (plugin_dir / "Scripts").mkdir(parents=True)

    with patch("platform.system", return_value="Windows"):
        env = plugins._sandbox_env(plugin_dir, {})

    path_parts = env["PATH"].split(os.pathsep)
    assert str(plugin_dir / ".venv" / "Scripts") in path_parts
    assert str(plugin_dir / "Scripts") in path_parts

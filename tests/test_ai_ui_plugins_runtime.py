import asyncio
import json
import os
import subprocess
import time
from types import SimpleNamespace
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


async def _wait_for_log_contains(log_path, needle: str, timeout: float = 3.0) -> str:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    last = ""
    while loop.time() < deadline:
        if log_path.exists():
            last = log_path.read_text(encoding="utf-8", errors="replace")
            if needle in last:
                return last
        await asyncio.sleep(0.05)
    return last


@pytest.fixture(autouse=True)
def _clear_running_processes():
    plugins._running_processes.clear()
    with plugins._codex_auth_lock:
        plugins._codex_auth_sessions.clear()
    with plugins._qwen_auth_lock:
        plugins._qwen_auth_sessions.clear()
    with plugins._gemini_auth_lock:
        plugins._gemini_auth_sessions.clear()
    yield
    plugins._running_processes.clear()
    with plugins._codex_auth_lock:
        plugins._codex_auth_sessions.clear()
    with plugins._qwen_auth_lock:
        plugins._qwen_auth_sessions.clear()
    with plugins._gemini_auth_lock:
        plugins._gemini_auth_sessions.clear()


def test_is_plugin_running_ignores_shared_port_fallback(tmp_path):
    plugin_dir = tmp_path / "counter-template"
    _write_manifest(plugin_dir, 8000)

    with (
        patch("pocketpaw.ai_ui.plugins.get_plugins_dir", return_value=tmp_path),
        patch("pocketpaw.ai_ui.plugins._read_pid", return_value=None),
        patch("pocketpaw.ai_ui.plugins._is_port_listening", return_value=True),
        patch("pocketpaw.ai_ui.plugins._is_port_unique_to_plugin", return_value=False),
    ):
        assert plugins._is_plugin_running("counter-template", plugin_dir) is False


@pytest.mark.asyncio
async def test_stop_plugin_shared_port_returns_ambiguous(tmp_path):
    plugin_a = tmp_path / "counter-template"
    plugin_b = tmp_path / "ai-fast-api"
    _write_manifest(plugin_a, 8000)
    _write_manifest(plugin_b, 8000)

    with (
        patch("pocketpaw.ai_ui.plugins.get_plugins_dir", return_value=tmp_path),
        patch("pocketpaw.ai_ui.plugins._read_pid", return_value=None),
        patch("pocketpaw.ai_ui.plugins._is_port_listening", return_value=True),
        patch("pocketpaw.ai_ui.plugins._get_pid_on_port") as mock_pid_on_port,
        patch("os.kill") as mock_kill,
    ):
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


def test_sandbox_env_posix_creates_python_shims(tmp_path):
    plugin_dir = tmp_path / "demo"
    plugin_dir.mkdir(parents=True)

    with patch("platform.system", return_value="Darwin"):
        env = plugins._sandbox_env(plugin_dir, {})

    shim_python = plugin_dir / "bin" / "python"
    shim_python3 = plugin_dir / "bin" / "python3"
    assert shim_python.exists()
    assert shim_python3.exists()
    assert str(plugin_dir / "bin") in env["PATH"].split(os.pathsep)


def test_sandbox_env_includes_host_home_hint(tmp_path):
    plugin_dir = tmp_path / "demo"
    plugin_dir.mkdir(parents=True)

    with (
        patch.dict(os.environ, {"HOME": "/Users/example"}, clear=False),
        patch("platform.system", return_value="Darwin"),
    ):
        env = plugins._sandbox_env(plugin_dir, {})

    assert env["HOME"] == str(plugin_dir)
    assert env["POCKETPAW_HOST_HOME"] == "/Users/example"


def test_posix_python3_shim_does_not_self_recurse(tmp_path):
    plugin_dir = tmp_path / "demo"
    plugin_dir.mkdir(parents=True)

    with patch("platform.system", return_value="Darwin"):
        plugins._sandbox_env(plugin_dir, {})

    shim_python3 = plugin_dir / "bin" / "python3"
    env = {
        "PATH": str(plugin_dir / "bin"),
    }
    proc = subprocess.run(
        [str(shim_python3), "-c", "import sys; print(sys.version_info[0])"],
        capture_output=True,
        text=True,
        timeout=5,
        env=env,
        check=False,
    )
    assert proc.returncode == 0
    assert (proc.stdout or "").strip() == "3"


def test_resolve_phase_command_windows_extracts_exec_from_start_sh(tmp_path):
    plugin_dir = tmp_path / "legacy"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "start.sh").write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "if [ -d .venv ]; then\n"
        "  source .venv/bin/activate\n"
        "fi\n"
        "exec python app.py --port 8000\n",
        encoding="utf-8",
    )
    manifest = {"start": "bash start.sh"}

    with patch("platform.system", return_value="Windows"), patch("shutil.which", return_value=None):
        cmd = plugins._resolve_phase_command(plugin_dir, manifest, "start")

    assert cmd == "python app.py --port 8000"


@pytest.mark.asyncio
async def test_launch_plugin_raises_when_process_exits_immediately(tmp_path):
    plugin_id = "fast-exit"
    plugin_dir = tmp_path / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "pocketpaw.json").write_text(
        json.dumps(
            {
                "name": "Fast Exit",
                "start": "echo boom && exit 1",
                "port": 9001,
            }
        ),
        encoding="utf-8",
    )

    with patch("pocketpaw.ai_ui.plugins.get_plugins_dir", return_value=tmp_path):
        with pytest.raises(RuntimeError, match="failed to start"):
            await plugins.launch_plugin(plugin_id)


@pytest.mark.asyncio
async def test_launch_plugin_python_shim_fallback_without_system_python(tmp_path):
    plugin_id = "shim-launch"
    plugin_dir = tmp_path / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "pocketpaw.json").write_text(
        json.dumps(
            {
                "name": "Shim Launch",
                "start": 'python -c "import time; time.sleep(2)"',
                "port": 9002,
            }
        ),
        encoding="utf-8",
    )

    with (
        patch("pocketpaw.ai_ui.plugins.get_plugins_dir", return_value=tmp_path),
        patch("pocketpaw.ai_ui.plugins._SYSTEM_PATHS", ""),
    ):
        result = await plugins.launch_plugin(plugin_id)
        assert result["status"] == "ok"
        stop_result = await plugins.stop_plugin(plugin_id)
        assert stop_result["status"] in {"ok", "stopped", "already_stopped"}


@pytest.mark.asyncio
async def test_launch_plugin_prefers_python_wrapper_over_shell_manifest(tmp_path):
    plugin_id = "wrapper-first"
    plugin_dir = tmp_path / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "pocketpaw.json").write_text(
        json.dumps(
            {
                "name": "Wrapper First",
                "start": "bash start.sh",
                "port": 9003,
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "start.sh").write_text("echo should-not-run && exit 1\n", encoding="utf-8")
    (plugin_dir / "pocketpaw_start.py").write_text(
        "import time\ntime.sleep(2)\n",
        encoding="utf-8",
    )

    with patch("pocketpaw.ai_ui.plugins.get_plugins_dir", return_value=tmp_path):
        result = await plugins.launch_plugin(plugin_id)
        assert result["status"] == "ok"
        stop_result = await plugins.stop_plugin(plugin_id)
        assert stop_result["status"] in {"ok", "stopped", "already_stopped"}


@pytest.mark.asyncio
async def test_launch_wan2gp_on_macos_injects_allow_mac_env(tmp_path):
    plugin_id = "wan2gp"
    plugin_dir = tmp_path / plugin_id
    plugin_dir.mkdir(parents=True)
    start_cmd = (
        "python -c "
        "\"import os,time; print('ALLOW_MAC=' + os.getenv('WAN2GP_ALLOW_MAC', '')); time.sleep(2)\""
    )
    (plugin_dir / "pocketpaw.json").write_text(
        json.dumps(
            {
                "name": "Wan2GP",
                "start": start_cmd,
                "port": 9004,
            }
        ),
        encoding="utf-8",
    )

    with (
        patch("pocketpaw.ai_ui.plugins.get_plugins_dir", return_value=tmp_path),
        patch("platform.system", return_value="Darwin"),
        patch(
            "pocketpaw.ai_ui.builtins.get_registry",
            return_value={},
        ),
    ):
        result = await plugins.launch_plugin(plugin_id)
        assert result["status"] == "ok"
        logs = await _wait_for_log_contains(plugin_dir / ".pocketpaw.log", "ALLOW_MAC=1")
        assert "ALLOW_MAC=1" in logs
        stop_result = await plugins.stop_plugin(plugin_id)
        assert stop_result["status"] in {"ok", "stopped", "already_stopped"}


@pytest.mark.asyncio
async def test_launch_wan2gp_refreshes_builtin_overlay_files(tmp_path):
    plugin_id = "wan2gp"
    plugin_dir = tmp_path / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "pocketpaw.json").write_text(
        json.dumps(
            {
                "name": "Wan2GP",
                "start": "python pocketpaw_start.py",
                "port": 9005,
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "pocketpaw_start.py").write_text(
        "raise SystemExit('stale-script-should-not-run')\n",
        encoding="utf-8",
    )

    fresh_script = "import time\nprint('fresh-script-ran')\ntime.sleep(2)\n"

    with (
        patch("pocketpaw.ai_ui.plugins.get_plugins_dir", return_value=tmp_path),
        patch("platform.system", return_value="Darwin"),
        patch(
            "pocketpaw.ai_ui.builtins.get_registry",
            return_value={plugin_id: {"files": {"pocketpaw_start.py": fresh_script}}},
        ),
    ):
        result = await plugins.launch_plugin(plugin_id)
        assert result["status"] == "ok"
        logs = await _wait_for_log_contains(plugin_dir / ".pocketpaw.log", "fresh-script-ran")
        assert "fresh-script-ran" in logs
        stop_result = await plugins.stop_plugin(plugin_id)
        assert stop_result["status"] in {"ok", "stopped", "already_stopped"}


@pytest.mark.asyncio
async def test_install_plugin_blocks_unsupported_builtin(tmp_path):
    with (
        patch("pocketpaw.ai_ui.plugins.get_plugins_dir", return_value=tmp_path),
        patch("pocketpaw.ai_ui.builtins.platform.system", return_value="Darwin"),
        patch("pocketpaw.ai_ui.builtins.platform.machine", return_value="arm64"),
    ):
        with pytest.raises(ValueError, match="unavailable on macOS arm64"):
            await plugins.install_plugin("builtin:wan2gp")


def test_resolve_chat_model_from_env_codex():
    env = {"LLM_BACKEND": "codex", "CODEX_MODEL": "gpt-5.2"}
    assert plugins._resolve_chat_model_from_env(env) == "gpt-5.2"


def test_resolve_chat_model_from_env_qwen():
    env = {"LLM_BACKEND": "qwen", "QWEN_MODEL": "qwen3-coder-plus"}
    assert plugins._resolve_chat_model_from_env(env) == "qwen3-coder-plus"


def test_resolve_chat_model_from_env_gemini():
    env = {"LLM_BACKEND": "gemini", "GEMINI_MODEL": "gemini-2.5-pro"}
    assert plugins._resolve_chat_model_from_env(env) == "gemini-2.5-pro"


def test_resolve_chat_model_from_env_auto():
    env = {"LLM_BACKEND": "auto", "AUTO_MODEL": "gpt-4.1"}
    assert plugins._resolve_chat_model_from_env(env) == "gpt-4.1"


def test_test_plugin_connection_uses_codex_model(tmp_path):
    plugin_id = "ai-fast-api"
    plugin_dir = tmp_path / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "pocketpaw.json").write_text(
        json.dumps(
            {
                "name": "AI Fast API",
                "env": {
                    "HOST": "0.0.0.0",
                    "PORT": "8000",
                    "LLM_BACKEND": "codex",
                    "CODEX_MODEL": "gpt-5.2",
                },
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, str] = {}

    class DummyResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "pong"}}]}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json):
            captured["url"] = url
            captured["model"] = json.get("model")
            return DummyResponse()

    with (
        patch("pocketpaw.ai_ui.plugins.get_plugins_dir", return_value=tmp_path),
        patch("httpx.Client", DummyClient),
    ):
        result = plugins.test_plugin_connection(plugin_id)

    assert result["ok"] is True
    assert captured["model"] == "gpt-5.2"
    assert captured["url"].startswith("http://127.0.0.1:8000")


def test_test_plugin_connection_uses_qwen_model(tmp_path):
    plugin_id = "ai-fast-api"
    plugin_dir = tmp_path / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "pocketpaw.json").write_text(
        json.dumps(
            {
                "name": "AI Fast API",
                "env": {
                    "HOST": "0.0.0.0",
                    "PORT": "8000",
                    "LLM_BACKEND": "qwen",
                    "QWEN_MODEL": "qwen3-coder-plus",
                },
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, str] = {}

    class DummyResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "pong"}}]}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json):
            captured["url"] = url
            captured["model"] = json.get("model")
            return DummyResponse()

    with (
        patch("pocketpaw.ai_ui.plugins.get_plugins_dir", return_value=tmp_path),
        patch("httpx.Client", DummyClient),
    ):
        result = plugins.test_plugin_connection(plugin_id)

    assert result["ok"] is True
    assert captured["model"] == "qwen3-coder-plus"
    assert captured["url"].startswith("http://127.0.0.1:8000")


def test_test_plugin_connection_uses_gemini_model(tmp_path):
    plugin_id = "ai-fast-api"
    plugin_dir = tmp_path / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "pocketpaw.json").write_text(
        json.dumps(
            {
                "name": "AI Fast API",
                "env": {
                    "HOST": "0.0.0.0",
                    "PORT": "8000",
                    "LLM_BACKEND": "gemini",
                    "GEMINI_MODEL": "gemini-2.5-flash",
                },
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, str] = {}

    class DummyResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "pong"}}]}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json):
            captured["url"] = url
            captured["model"] = json.get("model")
            return DummyResponse()

    with (
        patch("pocketpaw.ai_ui.plugins.get_plugins_dir", return_value=tmp_path),
        patch("httpx.Client", DummyClient),
    ):
        result = plugins.test_plugin_connection(plugin_id)

    assert result["ok"] is True
    assert captured["model"] == "gemini-2.5-flash"
    assert captured["url"].startswith("http://127.0.0.1:8000")


def test_test_plugin_connection_uses_auto_model(tmp_path):
    plugin_id = "ai-fast-api"
    plugin_dir = tmp_path / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "pocketpaw.json").write_text(
        json.dumps(
            {
                "name": "AI Fast API",
                "env": {
                    "HOST": "0.0.0.0",
                    "PORT": "8000",
                    "LLM_BACKEND": "auto",
                    "AUTO_MODEL": "gpt-4.1",
                },
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, str] = {}

    class DummyResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "pong"}}]}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json):
            captured["url"] = url
            captured["model"] = json.get("model")
            return DummyResponse()

    with (
        patch("pocketpaw.ai_ui.plugins.get_plugins_dir", return_value=tmp_path),
        patch("httpx.Client", DummyClient),
    ):
        result = plugins.test_plugin_connection(plugin_id)

    assert result["ok"] is True
    assert captured["model"] == "gpt-4.1"
    assert captured["url"].startswith("http://127.0.0.1:8000")


def test_chat_completion_proxy_uses_codex_model(tmp_path):
    plugin_id = "ai-fast-api"
    plugin_dir = tmp_path / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "pocketpaw.json").write_text(
        json.dumps(
            {
                "name": "AI Fast API",
                "env": {
                    "HOST": "0.0.0.0",
                    "PORT": "8000",
                    "LLM_BACKEND": "codex",
                    "CODEX_MODEL": "gpt-5.2",
                },
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, str] = {}

    class DummyResponse:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "ok"}}]}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json):
            captured["url"] = url
            captured["model"] = json.get("model")
            return DummyResponse()

    with (
        patch("pocketpaw.ai_ui.plugins.get_plugins_dir", return_value=tmp_path),
        patch("httpx.Client", DummyClient),
    ):
        response = plugins.chat_completion_proxy(plugin_id, [{"role": "user", "content": "hi"}])

    assert response["choices"][0]["message"]["content"] == "ok"
    assert captured["model"] == "gpt-5.2"
    assert captured["url"].startswith("http://127.0.0.1:8000")


def test_get_codex_auth_status_logged_in():
    completed = SimpleNamespace(returncode=0, stdout="", stderr="Logged in using ChatGPT\n")
    with (
        patch("pocketpaw.ai_ui.plugins._resolve_codex_bin", return_value="/usr/local/bin/codex"),
        patch("subprocess.run", return_value=completed),
    ):
        status = plugins.get_codex_auth_status()
    assert status["ok"] is True
    assert status["logged_in"] is True


def test_start_codex_device_auth_without_codex_binary():
    with patch("pocketpaw.ai_ui.plugins._resolve_codex_bin", return_value=None):
        result = plugins.start_codex_device_auth()
    assert result["ok"] is False
    assert result["status"] == "error"


def test_get_codex_device_auth_status_not_found():
    result = plugins.get_codex_device_auth_status("missing-session")
    assert result["ok"] is False
    assert result["status"] == "not_found"


def test_get_qwen_auth_status_no_cli():
    with patch("pocketpaw.ai_ui.plugins._resolve_qwen_command", return_value=None):
        status = plugins.get_qwen_auth_status()
    assert status["ok"] is False
    assert status["logged_in"] is False


def test_get_qwen_auth_status_logged_in_from_creds(tmp_path):
    qwen_dir = tmp_path / ".qwen"
    qwen_dir.mkdir(parents=True)
    creds_path = qwen_dir / "oauth_creds.json"
    creds_path.write_text(
        json.dumps(
            {
                "access_token": "token",
                "refresh_token": "refresh",
                "expiry_date": int((time.time() + 3600) * 1000),
                "resource_url": "portal.qwen.ai",
            }
        ),
        encoding="utf-8",
    )
    with (
        patch("pocketpaw.ai_ui.plugins._resolve_qwen_command", return_value=["qwen"]),
        patch("pathlib.Path.home", return_value=tmp_path),
    ):
        status = plugins.get_qwen_auth_status()
    assert status["ok"] is True
    assert status["logged_in"] is True


def test_start_qwen_device_auth_without_qwen_binary():
    with patch("pocketpaw.ai_ui.plugins._resolve_qwen_command", return_value=None):
        result = plugins.start_qwen_device_auth()
    assert result["ok"] is False
    assert result["status"] == "error"


def test_get_qwen_device_auth_status_not_found():
    result = plugins.get_qwen_device_auth_status("missing-session")
    assert result["ok"] is False
    assert result["status"] == "not_found"


def test_get_gemini_auth_status_no_cli():
    with patch("pocketpaw.ai_ui.plugins._resolve_gemini_command", return_value=None):
        status = plugins.get_gemini_auth_status()
    assert status["ok"] is False
    assert status["logged_in"] is False


def test_get_gemini_auth_status_logged_in_from_creds(tmp_path):
    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir(parents=True)
    creds_path = gemini_dir / "oauth_creds.json"
    creds_path.write_text(
        json.dumps(
            {
                "access_token": "token",
                "refresh_token": "refresh",
                "expiry_date": int((time.time() + 3600) * 1000),
                "token_type": "Bearer",
            }
        ),
        encoding="utf-8",
    )
    with (
        patch("pocketpaw.ai_ui.plugins._resolve_gemini_command", return_value=["gemini"]),
        patch("pathlib.Path.home", return_value=tmp_path),
    ):
        status = plugins.get_gemini_auth_status()
    assert status["ok"] is True
    assert status["logged_in"] is True


def test_start_gemini_device_auth_without_gemini_binary():
    with patch("pocketpaw.ai_ui.plugins._resolve_gemini_command", return_value=None):
        result = plugins.start_gemini_device_auth()
    assert result["ok"] is False
    assert result["status"] == "error"


def test_get_gemini_device_auth_status_not_found():
    result = plugins.get_gemini_device_auth_status("missing-session")
    assert result["ok"] is False
    assert result["status"] == "not_found"

# Tests for Unified Agent Loop
# Updated for AgentEvent-based architecture (no more dict chunks)

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pocketpaw.agents.loop import AgentLoop, _extract_search_context_line
from pocketpaw.agents.protocol import AgentEvent
from pocketpaw.bus import Channel, InboundMessage


@pytest.fixture
def mock_bus():
    bus = MagicMock()
    bus.consume_inbound = AsyncMock()
    bus.publish_outbound = AsyncMock()
    bus.publish_system = AsyncMock()
    return bus


@pytest.fixture
def mock_memory():
    mem = MagicMock()
    mem.add_to_session = AsyncMock()
    mem.get_session_history = AsyncMock(return_value=[])
    mem.get_compacted_history = AsyncMock(return_value=[])
    mem.resolve_session_key = AsyncMock(side_effect=lambda k: k)
    return mem


@pytest.fixture
def mock_router():
    """Mock AgentRouter that yields AgentEvent objects."""
    router = MagicMock()

    async def mock_run(message, *, system_prompt=None, history=None, session_key=None):
        yield AgentEvent(type="message", content="Hello ")
        yield AgentEvent(type="message", content="world!")
        yield AgentEvent(
            type="tool_use",
            content="Using test_tool...",
            metadata={"name": "test_tool", "input": {}},
        )
        yield AgentEvent(
            type="tool_result",
            content="Tool completed",
            metadata={"name": "test_tool"},
        )
        yield AgentEvent(type="done", content="")

    router.run = mock_run
    router.stop = AsyncMock()
    return router


@patch("pocketpaw.agents.loop.get_message_bus")
@patch("pocketpaw.agents.loop.get_memory_manager")
@patch("pocketpaw.agents.loop.AgentContextBuilder")
@patch("pocketpaw.agents.loop.AgentRouter")
@pytest.mark.asyncio
async def test_agent_loop_process_message(
    mock_router_cls,
    mock_builder_cls,
    mock_get_memory,
    mock_get_bus,
    mock_bus,
    mock_memory,
    mock_router,
):
    """Test that AgentLoop processes messages through the router."""
    mock_get_bus.return_value = mock_bus
    mock_get_memory.return_value = mock_memory
    mock_router_cls.return_value = mock_router

    mock_builder_instance = mock_builder_cls.return_value
    mock_builder_instance.build_system_prompt = AsyncMock(return_value="System Prompt")

    with patch("pocketpaw.agents.loop.get_settings") as mock_settings:
        settings = MagicMock()
        settings.agent_backend = "claude_agent_sdk"
        settings.max_concurrent_conversations = 5
        mock_settings.return_value = settings

        with patch("pocketpaw.agents.loop.Settings") as mock_settings_cls:
            mock_settings_cls.load.return_value = settings

            loop = AgentLoop()

            msg = InboundMessage(
                channel=Channel.CLI,
                sender_id="user1",
                chat_id="chat1",
                content="Hello",
            )

            await loop._process_message(msg)

            mock_memory.add_to_session.assert_called()
            assert mock_bus.publish_outbound.call_count >= 2
            assert mock_bus.publish_system.call_count >= 1


@patch("pocketpaw.agents.loop.get_message_bus")
@patch("pocketpaw.agents.loop.get_memory_manager")
@patch("pocketpaw.agents.loop.AgentContextBuilder")
@pytest.mark.asyncio
async def test_agent_loop_reset_router(
    mock_builder_cls, mock_get_memory, mock_get_bus, mock_bus, mock_memory
):
    """Test that reset_router clears the router instance."""
    mock_get_bus.return_value = mock_bus
    mock_get_memory.return_value = mock_memory

    with patch("pocketpaw.agents.loop.get_settings") as mock_settings:
        settings = MagicMock()
        settings.agent_backend = "claude_agent_sdk"
        settings.max_concurrent_conversations = 5
        mock_settings.return_value = settings

        loop = AgentLoop()
        assert loop._router is None
        loop.reset_router()
        assert loop._router is None


@patch("pocketpaw.agents.loop.get_message_bus")
@patch("pocketpaw.agents.loop.get_memory_manager")
@patch("pocketpaw.agents.loop.AgentContextBuilder")
@patch("pocketpaw.agents.loop.AgentRouter")
@pytest.mark.asyncio
async def test_agent_loop_handles_error(
    mock_router_cls, mock_builder_cls, mock_get_memory, mock_get_bus, mock_bus, mock_memory
):
    """Test that AgentLoop handles errors gracefully."""
    mock_get_bus.return_value = mock_bus
    mock_get_memory.return_value = mock_memory

    error_router = MagicMock()

    async def mock_run_error(message, *, system_prompt=None, history=None, session_key=None):
        yield AgentEvent(type="error", content="Something went wrong")
        yield AgentEvent(type="done", content="")

    error_router.run = mock_run_error
    mock_router_cls.return_value = error_router

    mock_builder_instance = mock_builder_cls.return_value
    mock_builder_instance.build_system_prompt = AsyncMock(return_value="System Prompt")

    with patch("pocketpaw.agents.loop.get_settings") as mock_settings:
        settings = MagicMock()
        settings.agent_backend = "claude_agent_sdk"
        settings.max_concurrent_conversations = 5
        mock_settings.return_value = settings

        with patch("pocketpaw.agents.loop.Settings") as mock_settings_cls:
            mock_settings_cls.load.return_value = settings

            loop = AgentLoop()

            msg = InboundMessage(
                channel=Channel.CLI,
                sender_id="user1",
                chat_id="chat1",
                content="Hello",
            )

            await loop._process_message(msg)
            mock_bus.publish_system.assert_called()


@patch("pocketpaw.agents.loop.get_message_bus")
@patch("pocketpaw.agents.loop.get_memory_manager")
@patch("pocketpaw.agents.loop.AgentContextBuilder")
@patch("pocketpaw.agents.loop.AgentRouter")
@pytest.mark.asyncio
async def test_agent_loop_emits_tool_events(
    mock_router_cls,
    mock_builder_cls,
    mock_get_memory,
    mock_get_bus,
    mock_bus,
    mock_memory,
    mock_router,
):
    """Test that tool_use and tool_result events are emitted as SystemEvents."""
    mock_get_bus.return_value = mock_bus
    mock_get_memory.return_value = mock_memory
    mock_router_cls.return_value = mock_router

    mock_builder_instance = mock_builder_cls.return_value
    mock_builder_instance.build_system_prompt = AsyncMock(return_value="System Prompt")

    with patch("pocketpaw.agents.loop.get_settings") as mock_settings:
        settings = MagicMock()
        settings.agent_backend = "claude_agent_sdk"
        settings.max_concurrent_conversations = 5
        mock_settings.return_value = settings

        with patch("pocketpaw.agents.loop.Settings") as mock_settings_cls:
            mock_settings_cls.load.return_value = settings

            loop = AgentLoop()

            msg = InboundMessage(
                channel=Channel.CLI,
                sender_id="user1",
                chat_id="chat1",
                content="Run a tool",
            )

            await loop._process_message(msg)

            system_calls = mock_bus.publish_system.call_args_list
            event_types = [call[0][0].event_type for call in system_calls]

            assert "thinking" in event_types
            assert "tool_start" in event_types
            assert "tool_result" in event_types


@patch("pocketpaw.agents.loop.get_message_bus")
@patch("pocketpaw.agents.loop.get_memory_manager")
@patch("pocketpaw.agents.loop.AgentContextBuilder")
@patch("pocketpaw.agents.loop.get_command_handler")
@patch("pocketpaw.agents.loop.get_settings")
@pytest.mark.asyncio
async def test_agent_loop_ai_ui_plugins_local_intent(
    mock_get_settings,
    mock_get_cmd_handler,
    mock_builder_cls,
    mock_get_memory,
    mock_get_bus,
    mock_bus,
    mock_memory,
):
    """Natural-language AI UI plugin list queries should be handled locally."""
    settings = MagicMock()
    settings.agent_backend = "claude_agent_sdk"
    settings.max_concurrent_conversations = 5
    settings.injection_scan_enabled = False
    settings.welcome_hint_enabled = False
    mock_get_settings.return_value = settings

    cmd_handler = MagicMock()
    cmd_handler._on_settings_changed = None
    cmd_handler.is_command.return_value = False
    mock_get_cmd_handler.return_value = cmd_handler

    mock_get_bus.return_value = mock_bus
    mock_get_memory.return_value = mock_memory
    mock_builder_cls.return_value.build_system_prompt = AsyncMock(return_value="System Prompt")

    loop = AgentLoop()

    with patch("pocketpaw.ai_ui.summary.get_plugins_summary") as mock_summary:
        mock_summary.return_value = "AI UI plugins (1):\n- `demo` — Demo Plugin (running)"
        msg = InboundMessage(
            channel=Channel.WEBSOCKET,
            sender_id="user1",
            chat_id="chat1",
            content="check all ai ui plugins?",
        )
        await loop._process_message(msg)

    # First outbound is the local summary, second is stream_end marker.
    first = mock_bus.publish_outbound.call_args_list[0][0][0]
    second = mock_bus.publish_outbound.call_args_list[1][0][0]
    assert "AI UI plugins (1)" in first.content
    assert second.is_stream_end is True


@patch("pocketpaw.agents.loop.get_message_bus")
@patch("pocketpaw.agents.loop.get_memory_manager")
@patch("pocketpaw.agents.loop.AgentContextBuilder")
@patch("pocketpaw.agents.loop.get_command_handler")
@patch("pocketpaw.agents.loop.get_settings")
@pytest.mark.asyncio
async def test_agent_loop_ai_ui_stop_local_intent(
    mock_get_settings,
    mock_get_cmd_handler,
    mock_builder_cls,
    mock_get_memory,
    mock_get_bus,
    mock_bus,
    mock_memory,
):
    """Plain-language stop requests should stop installed AI UI plugins locally."""
    settings = MagicMock()
    settings.agent_backend = "claude_agent_sdk"
    settings.max_concurrent_conversations = 5
    settings.injection_scan_enabled = False
    settings.welcome_hint_enabled = False
    mock_get_settings.return_value = settings

    cmd_handler = MagicMock()
    cmd_handler._on_settings_changed = None
    cmd_handler.is_command.return_value = False
    mock_get_cmd_handler.return_value = cmd_handler

    mock_get_bus.return_value = mock_bus
    mock_get_memory.return_value = mock_memory
    mock_builder_cls.return_value.build_system_prompt = AsyncMock(return_value="System Prompt")

    loop = AgentLoop()

    with patch("pocketpaw.ai_ui.plugins.list_plugins") as mock_list, patch(
        "pocketpaw.ai_ui.plugins.stop_plugin"
    ) as mock_stop:
        mock_list.return_value = [{"id": "counter-template"}]
        mock_stop.return_value = {"status": "ok", "message": "Plugin 'counter-template' stopped"}
        msg = InboundMessage(
            channel=Channel.WEBSOCKET,
            sender_id="user1",
            chat_id="chat1",
            content="stop counter-template",
        )
        await loop._process_message(msg)

    first = mock_bus.publish_outbound.call_args_list[0][0][0]
    second = mock_bus.publish_outbound.call_args_list[1][0][0]
    assert "counter-template" in first.content
    assert second.is_stream_end is True
    mock_stop.assert_awaited_once_with("counter-template")


@patch("pocketpaw.agents.loop.get_message_bus")
@patch("pocketpaw.agents.loop.get_memory_manager")
@patch("pocketpaw.agents.loop.AgentContextBuilder")
@patch("pocketpaw.agents.loop.get_command_handler")
@patch("pocketpaw.agents.loop.get_settings")
@pytest.mark.asyncio
async def test_agent_loop_ai_ui_start_local_intent(
    mock_get_settings,
    mock_get_cmd_handler,
    mock_builder_cls,
    mock_get_memory,
    mock_get_bus,
    mock_bus,
    mock_memory,
):
    """Plain-language start requests should launch an installed AI UI plugin."""
    settings = MagicMock()
    settings.agent_backend = "claude_agent_sdk"
    settings.max_concurrent_conversations = 5
    settings.injection_scan_enabled = False
    settings.welcome_hint_enabled = False
    mock_get_settings.return_value = settings

    cmd_handler = MagicMock()
    cmd_handler._on_settings_changed = None
    cmd_handler.is_command.return_value = False
    mock_get_cmd_handler.return_value = cmd_handler

    mock_get_bus.return_value = mock_bus
    mock_get_memory.return_value = mock_memory
    mock_builder_cls.return_value.build_system_prompt = AsyncMock(return_value="System Prompt")

    loop = AgentLoop()

    with patch("pocketpaw.ai_ui.plugins.list_plugins") as mock_list, patch(
        "pocketpaw.ai_ui.plugins.launch_plugin"
    ) as mock_launch, patch("pocketpaw.ai_ui.plugins.get_plugin") as mock_get_plugin:
        mock_list.return_value = [{"id": "counter-template", "name": "Counter Template"}]
        mock_launch.return_value = {
            "status": "ok",
            "message": "Plugin 'counter-template' launched on port 7860",
        }
        mock_get_plugin.return_value = {
            "id": "counter-template",
            "port": 7860,
            "web_view_path": "/",
        }
        msg = InboundMessage(
            channel=Channel.WEBSOCKET,
            sender_id="user1",
            chat_id="chat1",
            content="start counter-template",
        )
        await loop._process_message(msg)

    first = mock_bus.publish_outbound.call_args_list[0][0][0]
    second = mock_bus.publish_outbound.call_args_list[1][0][0]
    assert "counter-template" in first.content
    assert "#/ai-ui/plugin/counter-template/web" in first.content
    assert "http://localhost:7860/" in first.content
    assert second.is_stream_end is True
    mock_launch.assert_awaited_once_with("counter-template")


@patch("pocketpaw.agents.loop.get_message_bus")
@patch("pocketpaw.agents.loop.get_memory_manager")
@patch("pocketpaw.agents.loop.AgentContextBuilder")
@patch("pocketpaw.agents.loop.get_command_handler")
@patch("pocketpaw.agents.loop.get_settings")
@pytest.mark.asyncio
async def test_agent_loop_ai_ui_start_local_intent_installs_from_gallery(
    mock_get_settings,
    mock_get_cmd_handler,
    mock_builder_cls,
    mock_get_memory,
    mock_get_bus,
    mock_bus,
    mock_memory,
):
    """If missing, start intent should install from gallery and then launch."""
    settings = MagicMock()
    settings.agent_backend = "claude_agent_sdk"
    settings.max_concurrent_conversations = 5
    settings.injection_scan_enabled = False
    settings.welcome_hint_enabled = False
    mock_get_settings.return_value = settings

    cmd_handler = MagicMock()
    cmd_handler._on_settings_changed = None
    cmd_handler.is_command.return_value = False
    mock_get_cmd_handler.return_value = cmd_handler

    mock_get_bus.return_value = mock_bus
    mock_get_memory.return_value = mock_memory
    mock_builder_cls.return_value.build_system_prompt = AsyncMock(return_value="System Prompt")

    loop = AgentLoop()

    with patch("pocketpaw.ai_ui.plugins.list_plugins") as mock_list, patch(
        "pocketpaw.ai_ui.builtins.get_gallery"
    ) as mock_gallery, patch("pocketpaw.ai_ui.plugins.install_plugin") as mock_install, patch(
        "pocketpaw.ai_ui.plugins.launch_plugin"
    ) as mock_launch, patch("pocketpaw.ai_ui.plugins.get_plugin") as mock_get_plugin:
        mock_list.return_value = []
        mock_gallery.return_value = [
            {
                "id": "counter-template",
                "name": "Counter Template",
                "source": "builtin:counter-template",
            }
        ]
        mock_install.return_value = {
            "status": "ok",
            "message": "Counter Template has been added!",
            "plugin_id": "counter-template",
        }
        mock_launch.return_value = {
            "status": "ok",
            "message": "Plugin 'counter-template' launched on port 7860",
        }
        mock_get_plugin.return_value = {
            "id": "counter-template",
            "port": 7860,
            "web_view_path": "/",
        }
        msg = InboundMessage(
            channel=Channel.WEBSOCKET,
            sender_id="user1",
            chat_id="chat1",
            content="launch plugin counter-template",
        )
        await loop._process_message(msg)

    first = mock_bus.publish_outbound.call_args_list[0][0][0]
    second = mock_bus.publish_outbound.call_args_list[1][0][0]
    assert "Counter Template has been added!" in first.content
    assert "#/ai-ui/plugin/counter-template/web" in first.content
    assert second.is_stream_end is True
    mock_install.assert_awaited_once_with("builtin:counter-template")
    mock_launch.assert_awaited_once_with("counter-template")


@patch("pocketpaw.agents.loop.get_message_bus")
@patch("pocketpaw.agents.loop.get_memory_manager")
@patch("pocketpaw.agents.loop.AgentContextBuilder")
@patch("pocketpaw.agents.loop.AgentRouter")
@pytest.mark.asyncio
async def test_agent_loop_builds_context_and_passes_to_router(
    mock_router_cls,
    mock_builder_cls,
    mock_get_memory,
    mock_get_bus,
    mock_bus,
    mock_memory,
):
    """Test that AgentLoop builds system prompt and passes it to router."""
    mock_get_bus.return_value = mock_bus
    mock_get_memory.return_value = mock_memory

    captured_kwargs = {}

    async def capturing_run(message, *, system_prompt=None, history=None, session_key=None):
        captured_kwargs["system_prompt"] = system_prompt
        captured_kwargs["history"] = history
        yield AgentEvent(type="message", content="OK")
        yield AgentEvent(type="done", content="")

    router = MagicMock()
    router.run = capturing_run
    router.stop = AsyncMock()
    mock_router_cls.return_value = router

    mock_builder_instance = mock_builder_cls.return_value
    mock_builder_instance.build_system_prompt = AsyncMock(
        return_value="You are PocketPaw with identity and memory."
    )

    session_history = [
        {"role": "user", "content": "previous question"},
        {"role": "assistant", "content": "previous answer"},
    ]
    mock_memory.get_compacted_history = AsyncMock(return_value=session_history)

    with patch("pocketpaw.agents.loop.get_settings") as mock_settings:
        settings = MagicMock()
        settings.agent_backend = "claude_agent_sdk"
        settings.max_concurrent_conversations = 5
        mock_settings.return_value = settings

        with patch("pocketpaw.agents.loop.Settings") as mock_settings_cls:
            mock_settings_cls.load.return_value = settings

            loop = AgentLoop()

            msg = InboundMessage(
                channel=Channel.CLI,
                sender_id="user1",
                chat_id="chat1",
                content="What did I ask before?",
            )

            await loop._process_message(msg)

            mock_builder_instance.build_system_prompt.assert_called_once()
            mock_memory.get_compacted_history.assert_called_once()
            assert captured_kwargs["system_prompt"] == "You are PocketPaw with identity and memory."
            assert captured_kwargs["history"] == session_history


def test_extract_search_context_line():
    text = (
        "PocketPaw - Search Tavily - 2026-03-01 08:00 AM\n\n"
        "Search results for: ai news\n"
        "1. **Example**"
    )
    assert _extract_search_context_line(text) == "PocketPaw - Search Tavily - 2026-03-01 08:00 AM"
    assert _extract_search_context_line("no search header here") is None


@patch("pocketpaw.agents.loop.get_message_bus")
@patch("pocketpaw.agents.loop.get_memory_manager")
@patch("pocketpaw.agents.loop.AgentContextBuilder")
@patch("pocketpaw.agents.loop.AgentRouter")
@pytest.mark.asyncio
async def test_agent_loop_streams_web_search_context_line_to_chat(
    mock_router_cls,
    mock_builder_cls,
    mock_get_memory,
    mock_get_bus,
    mock_bus,
    mock_memory,
):
    mock_get_bus.return_value = mock_bus
    mock_get_memory.return_value = mock_memory

    async def mock_run(message, *, system_prompt=None, history=None, session_key=None):
        yield AgentEvent(
            type="tool_result",
            content=(
                "PocketPaw - Search Tavily - 2026-03-01 08:00 AM\n\n"
                "Search results for: latest ai news"
            ),
            metadata={"name": "web_search"},
        )
        yield AgentEvent(type="message", content="Here are the highlights.")
        yield AgentEvent(type="done", content="")

    router = MagicMock()
    router.run = mock_run
    router.stop = AsyncMock()
    mock_router_cls.return_value = router

    mock_builder_instance = mock_builder_cls.return_value
    mock_builder_instance.build_system_prompt = AsyncMock(return_value="System Prompt")

    with patch("pocketpaw.agents.loop.get_settings") as mock_settings:
        settings = MagicMock()
        settings.agent_backend = "claude_agent_sdk"
        settings.max_concurrent_conversations = 5
        mock_settings.return_value = settings

        with patch("pocketpaw.agents.loop.Settings") as mock_settings_cls:
            mock_settings_cls.load.return_value = settings
            loop = AgentLoop()

            msg = InboundMessage(
                channel=Channel.CLI,
                sender_id="user1",
                chat_id="chat1",
                content="get ai news",
            )
            await loop._process_message(msg)

    streamed_chunks = [
        call.args[0]
        for call in mock_bus.publish_outbound.call_args_list
        if call.args and getattr(call.args[0], "is_stream_chunk", False)
    ]
    assert any(
        "PocketPaw - Search Tavily - 2026-03-01 08:00 AM" in chunk.content
        for chunk in streamed_chunks
    )

"""Tests for OpenAI-compatible endpoint integration."""

from unittest.mock import AsyncMock, MagicMock, patch

from pocketpaw.agents.protocol import AgentEvent
from pocketpaw.llm.client import resolve_llm_client

# ---------------------------------------------------------------------------
# LLMClient — OpenAI-compatible provider detection
# ---------------------------------------------------------------------------


class TestLLMClientOpenAICompatible:
    """Verify LLMClient correctly handles OpenAI-compatible provider."""

    def test_provider_detection(self):
        """When llm_provider='openai_compatible', client detects it."""
        from pocketpaw.config import Settings

        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="http://localhost:4000/v1",
            openai_compatible_model="gpt-4o",
        )
        llm = resolve_llm_client(settings)
        assert llm.is_openai_compatible
        assert not llm.is_ollama
        assert not llm.is_anthropic

    def test_model_resolved(self):
        """Model name is set from openai_compatible_model."""
        from pocketpaw.config import Settings

        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="http://localhost:4000/v1",
            openai_compatible_model="my-custom-model",
        )
        llm = resolve_llm_client(settings)
        assert llm.model == "my-custom-model"

    def test_base_url_stored(self):
        """Base URL is carried through to the LLMClient."""
        from pocketpaw.config import Settings

        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="http://myhost:8080/v1",
            openai_compatible_model="model-x",
        )
        llm = resolve_llm_client(settings)
        assert llm.openai_compatible_base_url == "http://myhost:8080/v1"

    def test_api_key_carried(self):
        """API key flows to the LLMClient."""
        from pocketpaw.config import Settings

        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="http://localhost:4000/v1",
            openai_compatible_api_key="sk-custom-key",
            openai_compatible_model="model-x",
        )
        llm = resolve_llm_client(settings)
        assert llm.api_key == "sk-custom-key"

    def test_api_key_optional(self):
        """API key can be None."""
        from pocketpaw.config import Settings

        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="http://localhost:4000/v1",
            openai_compatible_model="model-x",
        )
        llm = resolve_llm_client(settings)
        assert llm.api_key is None


class TestLLMClientOpenAICompatibleEnv:
    """Verify env var construction for Claude SDK subprocess."""

    def test_env_vars_with_key(self):
        """Env dict includes ANTHROPIC_BASE_URL and ANTHROPIC_API_KEY."""
        from pocketpaw.config import Settings

        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="http://localhost:4000/v1",
            openai_compatible_api_key="sk-custom",
            openai_compatible_model="model-x",
        )
        llm = resolve_llm_client(settings)
        env = llm.to_sdk_env()
        assert env["ANTHROPIC_BASE_URL"] == "http://localhost:4000/v1"
        assert env["ANTHROPIC_API_KEY"] == "sk-custom"

    def test_env_vars_without_key(self):
        """Env dict uses 'not-needed' when no API key is set."""
        from pocketpaw.config import Settings

        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="http://localhost:4000/v1",
            openai_compatible_model="model-x",
        )
        llm = resolve_llm_client(settings)
        env = llm.to_sdk_env()
        assert env["ANTHROPIC_BASE_URL"] == "http://localhost:4000/v1"
        assert env["ANTHROPIC_API_KEY"] == "not-needed"


class TestLLMClientOpenAICompatibleClient:
    """Verify Anthropic client creation for OpenAI-compatible provider."""

    @patch("anthropic.AsyncAnthropic")
    def test_creates_client_with_base_url(self, mock_anthropic):
        """create_anthropic_client() uses the custom base URL."""
        from pocketpaw.config import Settings

        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="http://localhost:4000/v1",
            openai_compatible_api_key="sk-test",
            openai_compatible_model="model-x",
        )
        llm = resolve_llm_client(settings)
        llm.create_anthropic_client()

        mock_anthropic.assert_called_once_with(
            base_url="http://localhost:4000/v1",
            api_key="sk-test",
            timeout=120.0,
            max_retries=1,
        )

    @patch("anthropic.AsyncAnthropic")
    def test_creates_client_without_key(self, mock_anthropic):
        """create_anthropic_client() uses 'not-needed' when no key."""
        from pocketpaw.config import Settings

        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="http://localhost:4000/v1",
            openai_compatible_model="model-x",
        )
        llm = resolve_llm_client(settings)
        llm.create_anthropic_client()

        mock_anthropic.assert_called_once_with(
            base_url="http://localhost:4000/v1",
            api_key="not-needed",
            timeout=120.0,
            max_retries=1,
        )


class TestLLMClientOpenAICompatibleErrors:
    """Verify error formatting for OpenAI-compatible provider."""

    def test_connection_error(self):
        """Connection errors show the base URL."""
        from pocketpaw.config import Settings

        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="http://localhost:4000/v1",
            openai_compatible_model="model-x",
        )
        llm = resolve_llm_client(settings)
        msg = llm.format_api_error(ConnectionError("Connection refused"))
        assert "localhost:4000" in msg
        assert "Cannot connect" in msg

    def test_generic_error(self):
        """Generic errors include the base URL in the message."""
        from pocketpaw.config import Settings

        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="http://localhost:4000/v1",
            openai_compatible_model="model-x",
        )
        llm = resolve_llm_client(settings)
        msg = llm.format_api_error(RuntimeError("Something went wrong"))
        assert "OpenAI-compatible" in msg
        assert "localhost:4000" in msg

    def test_model_not_found_via_stderr(self):
        """When stderr contains model error, surfaces model name and hint."""
        from pocketpaw.config import Settings

        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="https://integrate.api.nvidia.com/v1",
            openai_compatible_model="moonshotai/kimi-k2.5",
        )
        llm = resolve_llm_client(settings)
        msg = llm.format_api_error(
            RuntimeError("Command failed with exit code 1"),
            stderr=(
                "There's an issue with the selected model (moonshotai/kimi-k2.5). "
                "It may not exist or you may not have access to it."
            ),
        )
        assert "moonshotai/kimi-k2.5" in msg
        assert "not available" in msg
        assert "nvidia.com" in msg
        # Should NOT say "server is running"
        assert "server" not in msg.lower() or "running" not in msg.lower()

    def test_stderr_surfaced_in_generic_error(self):
        """When stderr has content, it replaces the generic error message."""
        from pocketpaw.config import Settings

        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="http://localhost:4000/v1",
            openai_compatible_model="model-x",
        )
        llm = resolve_llm_client(settings)
        msg = llm.format_api_error(
            RuntimeError("Command failed with exit code 1"),
            stderr="Rate limit exceeded. Try again later.",
        )
        assert "Rate limit exceeded" in msg

    def test_auth_error(self):
        """Authentication errors suggest checking API key."""
        from pocketpaw.config import Settings

        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="http://localhost:4000/v1",
            openai_compatible_model="model-x",
        )
        llm = resolve_llm_client(settings)
        msg = llm.format_api_error(
            RuntimeError("Unauthorized"),
            stderr="Authentication failed: invalid API key",
        )
        assert "Authentication" in msg




# ---------------------------------------------------------------------------
# Claude SDK + OpenAI-compatible (logic tests via LLMClient)
# ---------------------------------------------------------------------------


class TestClaudeSDKOpenAICompatibleLogic:
    """Test OpenAI-compatible provider detection logic using LLMClient."""

    def test_smart_routing_skipped(self):
        """Verify smart routing skip condition for OpenAI-compatible."""
        from pocketpaw.config import Settings

        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="http://localhost:4000/v1",
            openai_compatible_model="model-x",
            smart_routing_enabled=True,
        )
        llm = resolve_llm_client(settings)
        should_route = (
            settings.smart_routing_enabled and not llm.is_ollama and not llm.is_openai_compatible
        )
        assert should_route is False

    def test_smart_routing_enabled_for_anthropic(self):
        """Verify smart routing is NOT skipped for Anthropic."""
        from pocketpaw.config import Settings

        settings = Settings(
            llm_provider="anthropic",
            anthropic_api_key="sk-test",
            smart_routing_enabled=True,
        )
        llm = resolve_llm_client(settings)
        should_route = (
            settings.smart_routing_enabled and not llm.is_ollama and not llm.is_openai_compatible
        )
        assert should_route is True




# ---------------------------------------------------------------------------
# check_openai_compatible CLI
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Claude SDK backend — OpenAI-compatible routing & streaming
# ---------------------------------------------------------------------------


def _make_openai_settings(**overrides):
    """Create a Settings-like mock configured for openai_compatible."""
    defaults = {
        "agent_backend": "claude_agent_sdk",
        "claude_sdk_provider": "openai_compatible",
        "claude_sdk_model": "",
        "claude_sdk_max_turns": 100,
        "tool_profile": "full",
        "tools_allow": [],
        "tools_deny": [],
        "smart_routing_enabled": False,
        "llm_provider": "openai_compatible",
        "openai_compatible_base_url": "http://localhost:8000/v1",
        "openai_compatible_api_key": "test-key",
        "openai_compatible_model": "gpt-4o-mini",
        "openai_compatible_max_tokens": 0,
        "anthropic_api_key": "",
        "anthropic_model": "claude-sonnet-4-6",
        "openai_api_key": "",
        "openai_model": "",
        "ollama_model": "",
        "ollama_host": "http://localhost:11434",
        "bypass_permissions": False,
        "file_jail_path": "/tmp",
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _make_claude_sdk(settings=None):
    """Create a ClaudeSDKBackend with mocked SDK imports."""
    from pocketpaw.agents.claude_sdk import ClaudeSDKBackend

    s = settings or _make_openai_settings()
    with patch("pocketpaw.agents.claude_sdk.ClaudeSDKBackend._initialize"):
        sdk = ClaudeSDKBackend(s)
    sdk._sdk_available = True
    sdk._cli_available = True
    return sdk


class _FakeChunk:
    """Simulates an OpenAI streaming chunk."""

    def __init__(self, text):
        choice = MagicMock()
        choice.delta.content = text
        self.choices = [choice]


class _FakeAsyncStream:
    """Async iterator that yields chunks."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class TestClaudeSDKOpenAICompatibleRouting:
    """Verify openai_compatible provider bypasses CLI and uses OpenAI SDK."""

    async def test_routes_through_openai_path(self):
        """openai_compatible provider should NOT touch the Claude CLI."""
        sdk = _make_claude_sdk()
        chunks = [_FakeChunk("Hello"), _FakeChunk(" world")]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_FakeAsyncStream(chunks)
        )

        fake_llm = MagicMock()
        fake_llm.is_openai_compatible = True
        fake_llm.is_ollama = False
        fake_llm.is_gemini = False
        fake_llm.model = "gpt-4o-mini"
        fake_llm.create_openai_client.return_value = mock_client

        with patch("pocketpaw.llm.client.resolve_llm_client", return_value=fake_llm):
            events = []
            async for ev in sdk.run("ping", system_prompt="You are helpful."):
                events.append(ev)

        types = [e.type for e in events]
        assert "message" in types
        assert "done" in types
        texts = "".join(e.content for e in events if e.type == "message")
        assert texts == "Hello world"

    async def test_streams_all_chunks(self):
        """All streamed chunks arrive as message events."""
        sdk = _make_claude_sdk()
        chunk_texts = ["A", "B", "C", "D"]
        chunks = [_FakeChunk(t) for t in chunk_texts]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_FakeAsyncStream(chunks)
        )

        fake_llm = MagicMock()
        fake_llm.is_openai_compatible = True
        fake_llm.is_ollama = False
        fake_llm.is_gemini = False
        fake_llm.model = "gpt-4o-mini"
        fake_llm.create_openai_client.return_value = mock_client

        with patch("pocketpaw.llm.client.resolve_llm_client", return_value=fake_llm):
            events = []
            async for ev in sdk.run("hello"):
                events.append(ev)

        msg_events = [e for e in events if e.type == "message"]
        assert len(msg_events) == 4
        assert [e.content for e in msg_events] == chunk_texts

    async def test_stop_flag_breaks_stream(self):
        """Setting stop flag mid-stream stops yielding."""
        sdk = _make_claude_sdk()
        chunks = [_FakeChunk("A"), _FakeChunk("B"), _FakeChunk("C")]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_FakeAsyncStream(chunks)
        )

        fake_llm = MagicMock()
        fake_llm.is_openai_compatible = True
        fake_llm.is_ollama = False
        fake_llm.is_gemini = False
        fake_llm.model = "gpt-4o-mini"
        fake_llm.create_openai_client.return_value = mock_client

        with patch("pocketpaw.llm.client.resolve_llm_client", return_value=fake_llm):
            events = []
            async for ev in sdk.run("hello"):
                events.append(ev)
                if ev.type == "message" and ev.content == "A":
                    sdk._stop_flag = True

        msg_events = [e for e in events if e.type == "message"]
        assert len(msg_events) == 1
        assert msg_events[0].content == "A"

    async def test_error_yields_error_event(self):
        """API errors produce an error event, not a crash."""
        sdk = _make_claude_sdk()
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=ConnectionError("Connection refused")
        )

        fake_llm = MagicMock()
        fake_llm.is_openai_compatible = True
        fake_llm.is_ollama = False
        fake_llm.is_gemini = False
        fake_llm.model = "gpt-4o-mini"
        fake_llm.create_openai_client.return_value = mock_client
        fake_llm.format_api_error.return_value = "❌ Connection refused"

        with patch("pocketpaw.llm.client.resolve_llm_client", return_value=fake_llm):
            events = []
            async for ev in sdk.run("hello"):
                events.append(ev)

        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) == 1
        assert "Connection refused" in error_events[0].content

    async def test_history_passed_to_api(self):
        """Conversation history is included in the messages list."""
        sdk = _make_claude_sdk()
        chunks = [_FakeChunk("reply")]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_FakeAsyncStream(chunks)
        )

        fake_llm = MagicMock()
        fake_llm.is_openai_compatible = True
        fake_llm.is_ollama = False
        fake_llm.is_gemini = False
        fake_llm.model = "gpt-4o-mini"
        fake_llm.create_openai_client.return_value = mock_client

        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]

        with patch("pocketpaw.llm.client.resolve_llm_client", return_value=fake_llm):
            events = []
            async for ev in sdk.run("ping", history=history):
                events.append(ev)

        call_kwargs = mock_client.chat.completions.create.call_args
        messages = call_kwargs.kwargs.get("messages") or call_kwargs[1].get("messages")
        roles = [m["role"] for m in messages]
        assert roles == ["system", "user", "assistant", "user"]

    async def test_max_tokens_forwarded(self):
        """max_tokens from settings is forwarded to the API call."""
        settings = _make_openai_settings(openai_compatible_max_tokens=512)
        sdk = _make_claude_sdk(settings)
        chunks = [_FakeChunk("ok")]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_FakeAsyncStream(chunks)
        )

        fake_llm = MagicMock()
        fake_llm.is_openai_compatible = True
        fake_llm.is_ollama = False
        fake_llm.is_gemini = False
        fake_llm.model = "gpt-4o-mini"
        fake_llm.create_openai_client.return_value = mock_client

        with patch("pocketpaw.llm.client.resolve_llm_client", return_value=fake_llm):
            events = []
            async for ev in sdk.run("hi"):
                events.append(ev)

        call_kwargs = mock_client.chat.completions.create.call_args
        assert call_kwargs.kwargs.get("max_tokens") == 512

    async def test_no_max_tokens_when_zero(self):
        """max_tokens=0 means don't send max_tokens to the API."""
        settings = _make_openai_settings(openai_compatible_max_tokens=0)
        sdk = _make_claude_sdk(settings)
        chunks = [_FakeChunk("ok")]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_FakeAsyncStream(chunks)
        )

        fake_llm = MagicMock()
        fake_llm.is_openai_compatible = True
        fake_llm.is_ollama = False
        fake_llm.is_gemini = False
        fake_llm.model = "gpt-4o-mini"
        fake_llm.create_openai_client.return_value = mock_client

        with patch("pocketpaw.llm.client.resolve_llm_client", return_value=fake_llm):
            events = []
            async for ev in sdk.run("hi"):
                events.append(ev)

        call_kwargs = mock_client.chat.completions.create.call_args
        assert "max_tokens" not in call_kwargs.kwargs

    async def test_fallback_to_non_streaming(self):
        """When streaming fails, falls back to non-streaming."""
        sdk = _make_claude_sdk()

        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "non-stream reply"
        mock_response.choices = [mock_choice]

        async def _side_effect(**kwargs):
            if kwargs.get("stream"):
                raise RuntimeError("streaming not supported")
            return mock_response

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=_side_effect)

        fake_llm = MagicMock()
        fake_llm.is_openai_compatible = True
        fake_llm.is_ollama = False
        fake_llm.is_gemini = False
        fake_llm.model = "gpt-4o-mini"
        fake_llm.openai_compatible_base_url = "http://localhost:8000/v1"
        fake_llm.create_openai_client.return_value = mock_client

        with patch("pocketpaw.llm.client.resolve_llm_client", return_value=fake_llm):
            events = []
            async for ev in sdk.run("hi"):
                events.append(ev)

        types = [e.type for e in events]
        assert "message" in types
        assert "done" in types
        texts = "".join(e.content for e in events if e.type == "message")
        assert texts == "non-stream reply"


class TestCheckOpenAICompatible:
    """Tests for the --check-openai-compatible CLI command."""

    async def test_empty_base_url_returns_1(self):
        """When base URL is empty, returns exit code 1."""
        from pocketpaw.__main__ import check_openai_compatible
        from pocketpaw.config import Settings

        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="",
            openai_compatible_model="model-x",
        )
        exit_code = await check_openai_compatible(settings)
        assert exit_code == 1

    async def test_empty_model_returns_1(self):
        """When model is empty, returns exit code 1."""
        from pocketpaw.__main__ import check_openai_compatible
        from pocketpaw.config import Settings

        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="http://localhost:4000/v1",
            openai_compatible_model="",
        )
        exit_code = await check_openai_compatible(settings)
        assert exit_code == 1

    async def test_api_failure_returns_1(self):
        """When the API call fails, returns exit code 1."""
        from pocketpaw.__main__ import check_openai_compatible
        from pocketpaw.config import Settings

        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="http://localhost:99999/v1",
            openai_compatible_model="model-x",
        )
        exit_code = await check_openai_compatible(settings)
        assert exit_code == 1

    async def test_success_with_tool_calling(self):
        """When API and tool calling succeed, returns exit code 0."""
        from pocketpaw.__main__ import check_openai_compatible
        from pocketpaw.config import Settings

        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="http://localhost:4000/v1",
            openai_compatible_model="model-x",
        )

        # Build OpenAI-format mock responses
        mock_msg1 = MagicMock()
        mock_msg1.content = "Hi there!"
        mock_msg1.tool_calls = [MagicMock()]  # has tool calls
        mock_choice1 = MagicMock()
        mock_choice1.message = mock_msg1
        mock_response1 = MagicMock()
        mock_response1.choices = [mock_choice1]

        mock_msg2 = MagicMock()
        mock_msg2.content = "4"
        mock_msg2.tool_calls = [MagicMock()]
        mock_choice2 = MagicMock()
        mock_choice2.message = mock_msg2
        mock_response2 = MagicMock()
        mock_response2.choices = [mock_choice2]

        mock_oc = MagicMock()
        mock_oc.chat.completions.create = AsyncMock(side_effect=[mock_response1, mock_response2])

        with patch(
            "pocketpaw.llm.client.LLMClient.create_openai_client",
            return_value=mock_oc,
        ):
            exit_code = await check_openai_compatible(settings)
            assert exit_code == 0

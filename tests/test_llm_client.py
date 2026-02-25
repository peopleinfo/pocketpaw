"""Tests for the centralized LLMClient abstraction."""

import dataclasses
from unittest.mock import patch

import pytest

from pocketpaw.config import Settings
from pocketpaw.llm.client import LLMClient, _normalize_openai_base_url, resolve_llm_client

# ---------------------------------------------------------------------------
# resolve_llm_client
# ---------------------------------------------------------------------------


class TestResolveLLMClient:
    def test_resolve_auto_anthropic(self):
        """auto + anthropic key → anthropic provider."""
        settings = Settings(llm_provider="auto", anthropic_api_key="sk-ant")
        llm = resolve_llm_client(settings)
        assert llm.provider == "anthropic"
        assert llm.model == settings.anthropic_model
        assert llm.api_key == "sk-ant"
        assert llm.ollama_host  # always populated from settings

    def test_resolve_auto_openai(self):
        """auto + openai key only → openai provider."""
        settings = Settings(
            llm_provider="auto",
            anthropic_api_key=None,
            openai_api_key="sk-oai",
        )
        llm = resolve_llm_client(settings)
        assert llm.provider == "openai"
        assert llm.model == settings.openai_model
        assert llm.api_key == "sk-oai"

    def test_resolve_auto_ollama(self):
        """auto + no keys → ollama fallback."""
        settings = Settings(
            llm_provider="auto",
            anthropic_api_key=None,
            openai_api_key=None,
            ollama_host="http://myhost:11434",
            ollama_model="qwen2.5:7b",
        )
        llm = resolve_llm_client(settings)
        assert llm.provider == "ollama"
        assert llm.model == "qwen2.5:7b"
        assert llm.api_key is None
        assert llm.ollama_host == "http://myhost:11434"

    def test_resolve_explicit_ollama(self):
        """Explicit provider='ollama'."""
        settings = Settings(
            llm_provider="ollama",
            ollama_model="llama3.2",
            ollama_host="http://localhost:11434",
        )
        llm = resolve_llm_client(settings)
        assert llm.is_ollama
        assert not llm.is_anthropic
        assert llm.model == "llama3.2"

    def test_resolve_force_provider(self):
        """force_provider overrides settings."""
        settings = Settings(
            llm_provider="ollama",
            anthropic_api_key="sk-test",
            anthropic_model="claude-sonnet-4-5-20250929",
        )
        llm = resolve_llm_client(settings, force_provider="anthropic")
        assert llm.provider == "anthropic"
        assert llm.api_key == "sk-test"

    def test_resolve_auto_prefers_anthropic_over_openai(self):
        """When both keys exist, auto prefers anthropic."""
        settings = Settings(
            llm_provider="auto",
            anthropic_api_key="sk-ant",
            openai_api_key="sk-oai",
        )
        llm = resolve_llm_client(settings)
        assert llm.provider == "anthropic"


# ---------------------------------------------------------------------------
# create_anthropic_client
# ---------------------------------------------------------------------------


class TestCreateAnthropicClient:
    @patch("anthropic.AsyncAnthropic")
    def test_create_client_ollama(self, mock_cls):
        """Ollama client uses correct base_url, api_key, timeout, retries."""
        llm = LLMClient(
            provider="ollama",
            model="llama3.2",
            api_key=None,
            ollama_host="http://localhost:11434",
        )
        llm.create_anthropic_client()

        mock_cls.assert_called_once_with(
            base_url="http://localhost:11434",
            api_key="ollama",
            timeout=120.0,
            max_retries=1,
        )

    @patch("anthropic.AsyncAnthropic")
    def test_create_client_anthropic(self, mock_cls):
        """Anthropic client uses correct api_key, timeout, retries."""
        llm = LLMClient(
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
            api_key="sk-ant",
            ollama_host="http://localhost:11434",
        )
        llm.create_anthropic_client()

        mock_cls.assert_called_once_with(
            api_key="sk-ant",
            timeout=60.0,
            max_retries=2,
        )

    @patch("anthropic.AsyncAnthropic")
    def test_create_client_custom_timeout(self, mock_cls):
        """Custom timeout and retries are forwarded."""
        llm = LLMClient(
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
            api_key="sk-ant",
            ollama_host="http://localhost:11434",
        )
        llm.create_anthropic_client(timeout=30.0, max_retries=5)

        mock_cls.assert_called_once_with(
            api_key="sk-ant",
            timeout=30.0,
            max_retries=5,
        )

    def test_create_client_openai_raises(self):
        """OpenAI provider raises ValueError."""
        llm = LLMClient(
            provider="openai",
            model="gpt-4o",
            api_key="sk-oai",
            ollama_host="http://localhost:11434",
        )
        with pytest.raises(ValueError, match="OpenAI provider"):
            llm.create_anthropic_client()


# ---------------------------------------------------------------------------
# to_sdk_env
# ---------------------------------------------------------------------------


class TestToSdkEnv:
    def test_to_sdk_env_ollama(self):
        llm = LLMClient(
            provider="ollama",
            model="llama3.2",
            api_key=None,
            ollama_host="http://myhost:11434",
        )
        env = llm.to_sdk_env()
        assert env == {
            "ANTHROPIC_BASE_URL": "http://myhost:11434",
            "ANTHROPIC_API_KEY": "ollama",
        }

    def test_to_sdk_env_anthropic(self):
        llm = LLMClient(
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
            api_key="sk-real",
            ollama_host="http://localhost:11434",
        )
        env = llm.to_sdk_env()
        assert env == {"ANTHROPIC_API_KEY": "sk-real"}

    def test_to_sdk_env_no_key(self):
        llm = LLMClient(
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
            api_key=None,
            ollama_host="http://localhost:11434",
        )
        env = llm.to_sdk_env()
        assert env == {}


# ---------------------------------------------------------------------------
# format_api_error
# ---------------------------------------------------------------------------


class TestFormatApiError:
    def test_format_error_ollama_not_found(self):
        llm = LLMClient(
            provider="ollama",
            model="missing-model",
            api_key=None,
            ollama_host="http://localhost:11434",
        )
        msg = llm.format_api_error(Exception("model not_found"))
        assert "missing-model" in msg
        assert "not found" in msg.lower()

    def test_format_error_ollama_connection(self):
        llm = LLMClient(
            provider="ollama",
            model="llama3.2",
            api_key=None,
            ollama_host="http://localhost:11434",
        )
        msg = llm.format_api_error(Exception("Connection refused"))
        assert "Cannot connect" in msg
        assert "localhost:11434" in msg

    def test_format_error_ollama_generic(self):
        llm = LLMClient(
            provider="ollama",
            model="llama3.2",
            api_key=None,
            ollama_host="http://localhost:11434",
        )
        msg = llm.format_api_error(Exception("some weird error"))
        assert "Ollama error" in msg

    def test_format_error_anthropic_auth(self):
        llm = LLMClient(
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
            api_key="bad-key",
            ollama_host="http://localhost:11434",
        )
        msg = llm.format_api_error(Exception("Invalid API key"))
        assert "API key" in msg

    def test_format_error_anthropic_generic(self):
        llm = LLMClient(
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
            api_key="sk-test",
            ollama_host="http://localhost:11434",
        )
        msg = llm.format_api_error(Exception("rate limit exceeded"))
        assert "rate limit exceeded" in msg


# ---------------------------------------------------------------------------
# frozen immutability
# ---------------------------------------------------------------------------


class TestFrozen:
    def test_frozen(self):
        llm = LLMClient(
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
            api_key="sk-test",
            ollama_host="http://localhost:11434",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            llm.provider = "ollama"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _normalize_openai_base_url
# ---------------------------------------------------------------------------


class TestNormalizeOpenAIBaseURL:
    def test_strips_chat_completions(self):
        url = "http://localhost:8000/v1/chat/completions"
        assert _normalize_openai_base_url(url) == "http://localhost:8000/v1"

    def test_strips_completions(self):
        url = "http://localhost:8000/v1/completions"
        assert _normalize_openai_base_url(url) == "http://localhost:8000/v1"

    def test_strips_embeddings(self):
        url = "http://localhost:8000/v1/embeddings"
        assert _normalize_openai_base_url(url) == "http://localhost:8000/v1"

    def test_strips_trailing_slash(self):
        url = "http://localhost:8000/v1/chat/completions/"
        assert _normalize_openai_base_url(url) == "http://localhost:8000/v1"

    def test_no_op_for_clean_url(self):
        url = "http://localhost:8000/v1"
        assert _normalize_openai_base_url(url) == "http://localhost:8000/v1"

    def test_no_op_for_base_only(self):
        url = "http://localhost:8000"
        assert _normalize_openai_base_url(url) == "http://localhost:8000"

    def test_preserves_port_and_path(self):
        url = "https://api.example.com:9090/proxy/v1/chat/completions"
        assert _normalize_openai_base_url(url) == "https://api.example.com:9090/proxy/v1"

    def test_empty_string(self):
        assert _normalize_openai_base_url("") == ""


class TestResolveOpenAICompatibleNormalization:
    """Verify resolve_llm_client applies URL normalization."""

    def test_full_endpoint_url_normalized(self):
        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="http://localhost:8000/v1/chat/completions",
            openai_compatible_model="gpt-4o-mini",
        )
        llm = resolve_llm_client(settings)
        assert llm.openai_compatible_base_url == "http://localhost:8000/v1"

    def test_clean_url_unchanged(self):
        settings = Settings(
            llm_provider="openai_compatible",
            openai_compatible_base_url="http://localhost:8000/v1",
            openai_compatible_model="gpt-4o-mini",
        )
        llm = resolve_llm_client(settings)
        assert llm.openai_compatible_base_url == "http://localhost:8000/v1"

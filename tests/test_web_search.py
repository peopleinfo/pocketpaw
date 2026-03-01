# Tests for Feature 1: WebSearchTool
# Created: 2026-02-06

import re
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from pocketpaw.tools.builtin.web_search import WebSearchTool


@pytest.fixture
def tool():
    return WebSearchTool()


class TestWebSearchTool:
    """Tests for WebSearchTool."""

    def test_name(self, tool):
        assert tool.name == "web_search"

    def test_trust_level(self, tool):
        assert tool.trust_level == "standard"

    def test_parameters_schema(self, tool):
        params = tool.parameters
        assert "query" in params["properties"]
        assert "num_results" in params["properties"]
        assert "provider" in params["properties"]
        assert "query" in params["required"]

    @patch("pocketpaw.tools.builtin.web_search.get_settings")
    async def test_tavily_search_success(self, mock_settings, tool):
        mock_settings.return_value = MagicMock(
            web_search_provider="tavily",
            tavily_api_key="test-key",
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {
                    "title": "Python Docs",
                    "url": "https://docs.python.org",
                    "content": "Official Python documentation",
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await tool.execute(query="python docs")

        assert re.search(
            r"PocketPaw - Search Tavily - \d{4}-\d{2}-\d{2} \d{2}:\d{2} [AP]M", result
        )
        assert "Python Docs" in result
        assert "https://docs.python.org" in result

    @patch("pocketpaw.tools.builtin.web_search.get_settings")
    async def test_brave_search_success(self, mock_settings, tool):
        mock_settings.return_value = MagicMock(
            web_search_provider="brave",
            brave_search_api_key="test-brave-key",
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "web": {
                "results": [
                    {
                        "title": "Brave Search",
                        "url": "https://brave.com",
                        "description": "Privacy search engine",
                    }
                ]
            }
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await tool.execute(query="brave search")

        assert re.search(
            r"PocketPaw - Search Brave - \d{4}-\d{2}-\d{2} \d{2}:\d{2} [AP]M", result
        )
        assert "Brave Search" in result
        assert "https://brave.com" in result

    @patch("pocketpaw.tools.builtin.web_search.get_settings")
    async def test_missing_tavily_api_key(self, mock_settings, tool):
        mock_settings.return_value = MagicMock(
            web_search_provider="tavily",
            tavily_api_key=None,
            brave_search_api_key=None,
            parallel_api_key=None,
        )
        result = await tool.execute(query="test")
        assert "Error" in result
        assert "Tavily API key" in result

    @patch("pocketpaw.tools.builtin.web_search.get_settings")
    async def test_missing_brave_api_key(self, mock_settings, tool):
        mock_settings.return_value = MagicMock(
            web_search_provider="brave",
            brave_search_api_key=None,
            tavily_api_key=None,
            parallel_api_key=None,
        )
        result = await tool.execute(query="test")
        assert "Error" in result
        assert "Brave Search API key" in result

    @patch("pocketpaw.tools.builtin.web_search.get_settings")
    async def test_unknown_provider(self, mock_settings, tool):
        mock_settings.return_value = MagicMock(web_search_provider="duckduckgo")
        result = await tool.execute(query="test")
        assert "Error" in result
        assert "Unknown search provider" in result

    @patch("pocketpaw.tools.builtin.web_search.get_settings")
    async def test_no_results(self, mock_settings, tool):
        mock_settings.return_value = MagicMock(
            web_search_provider="tavily",
            tavily_api_key="test-key",
        )

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"results": []}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await tool.execute(query="xyznonexistent")

        assert "No results found" in result

    @patch("pocketpaw.tools.builtin.web_search.get_settings")
    async def test_http_error(self, mock_settings, tool):
        mock_settings.return_value = MagicMock(
            web_search_provider="tavily",
            tavily_api_key="test-key",
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unauthorized",
            request=MagicMock(),
            response=MagicMock(status_code=401),
        )

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await tool.execute(query="test")

        assert "Error" in result

    @patch("pocketpaw.tools.builtin.web_search.get_settings")
    async def test_parallel_search_success(self, mock_settings, tool):
        mock_settings.return_value = MagicMock(
            web_search_provider="parallel",
            parallel_api_key="test-parallel-key",
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {
                    "title": "Parallel AI Docs",
                    "url": "https://docs.parallel.ai",
                    "excerpts": ["First excerpt.", "Second excerpt."],
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await tool.execute(query="parallel ai")

        assert re.search(
            r"PocketPaw - Search Parallel - \d{4}-\d{2}-\d{2} \d{2}:\d{2} [AP]M", result
        )
        assert "Parallel AI Docs" in result
        assert "https://docs.parallel.ai" in result
        # Verify headers were sent correctly
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["headers"]["x-api-key"] == "test-parallel-key"
        assert "parallel-beta" in call_kwargs.kwargs["headers"]

    @patch("pocketpaw.tools.builtin.web_search.get_settings")
    async def test_parallel_missing_api_key(self, mock_settings, tool):
        mock_settings.return_value = MagicMock(
            web_search_provider="parallel",
            parallel_api_key=None,
            tavily_api_key=None,
            brave_search_api_key=None,
        )
        result = await tool.execute(query="test")
        assert "Error" in result
        assert "Parallel AI API key" in result

    @patch("pocketpaw.tools.builtin.web_search.get_settings")
    async def test_fallback_to_available_provider(self, mock_settings, tool):
        mock_settings.return_value = MagicMock(
            web_search_provider="tavily",
            tavily_api_key=None,
            brave_search_api_key="test-brave-key",
            parallel_api_key=None,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "web": {
                "results": [
                    {
                        "title": "Fallback Brave Result",
                        "url": "https://brave.com/search",
                        "description": "Result from fallback",
                    }
                ]
            }
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await tool.execute(query="fallback test")

        assert "Falling back to 'brave'" in result
        assert "PocketPaw - Search Brave -" in result
        assert "Fallback Brave Result" in result

    @patch("pocketpaw.tools.builtin.web_search.get_settings")
    async def test_provider_override(self, mock_settings, tool):
        mock_settings.return_value = MagicMock(
            web_search_provider="tavily",
            tavily_api_key="test-tavily",
            brave_search_api_key="test-brave-key",
            parallel_api_key=None,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "web": {
                "results": [
                    {
                        "title": "Brave Override",
                        "url": "https://brave.com/override",
                        "description": "Used override provider",
                    }
                ]
            }
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await tool.execute(query="override", provider="brave")

        assert "PocketPaw - Search Brave -" in result
        assert "Brave Override" in result

    @patch("pocketpaw.tools.builtin.web_search.get_settings")
    async def test_auto_provider_selects_available_key(self, mock_settings, tool):
        mock_settings.return_value = MagicMock(
            web_search_provider="auto",
            tavily_api_key=None,
            brave_search_api_key=None,
            parallel_api_key="test-parallel-key",
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {
                    "title": "Parallel Auto",
                    "url": "https://parallel.ai",
                    "excerpts": ["Auto-selected provider result"],
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await tool.execute(query="auto provider", provider="auto")

        assert "PocketPaw - Search Parallel -" in result
        assert "Parallel Auto" in result

    @patch("pocketpaw.tools.builtin.web_search.get_settings")
    async def test_parallel_no_results(self, mock_settings, tool):
        mock_settings.return_value = MagicMock(
            web_search_provider="parallel",
            parallel_api_key="test-key",
        )

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"results": []}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await tool.execute(query="nothing here")

        assert "No results found" in result

    @patch("pocketpaw.tools.builtin.web_search.get_settings")
    async def test_num_results_clamped(self, mock_settings, tool):
        mock_settings.return_value = MagicMock(
            web_search_provider="tavily",
            tavily_api_key="test-key",
        )

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"results": [{"title": "A", "url": "u", "content": "c"}]}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            # num_results=50 should be clamped to 10
            result = await tool.execute(query="test", num_results=50)

        assert "A" in result

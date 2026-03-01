# Web Search tool — search the web via Tavily or Brave APIs.
# Created: 2026-02-06
# Part of Phase 1 Quick Wins

import logging
from datetime import datetime
from typing import Any

import httpx

from pocketpaw.config import get_settings
from pocketpaw.tools.protocol import BaseTool

logger = logging.getLogger(__name__)

_TAVILY_URL = "https://api.tavily.com/search"
_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
_PARALLEL_SEARCH_URL = "https://api.parallel.ai/v1beta/search"


class WebSearchTool(BaseTool):
    """Search the web using Tavily, Brave, or Parallel AI Search API."""

    _PROVIDER_PRIORITY = ("tavily", "brave", "parallel")
    _PROVIDER_LABELS = {
        "tavily": "Tavily",
        "brave": "Brave",
        "parallel": "Parallel",
    }

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for current information. Returns a list of results "
            "with titles, URLs, and snippets. Useful for answering questions "
            "about recent events, looking up documentation, or finding resources."
        )

    @property
    def trust_level(self) -> str:
        return "standard"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return (default: 5, max: 10)",
                    "default": 5,
                },
                "provider": {
                    "type": "string",
                    "description": (
                        "Search provider override. Use 'auto' to pick the first provider "
                        "with a configured API key."
                    ),
                    "enum": ["auto", "tavily", "brave", "parallel"],
                },
            },
            "required": ["query"],
        }

    async def execute(  # type: ignore[override]
        self,
        query: str,
        num_results: int = 5,
        provider: str | None = None,
    ) -> str:
        """Execute a web search."""
        settings = get_settings()
        num_results = min(max(num_results, 1), 10)

        resolved_provider, fallback_note, error = self._resolve_provider(settings, provider)
        if error:
            return self._error(error)

        if resolved_provider == "tavily":
            result = await self._search_tavily(
                query,
                num_results,
                self._provider_key(settings, "tavily"),
            )
        elif resolved_provider == "brave":
            result = await self._search_brave(
                query,
                num_results,
                self._provider_key(settings, "brave"),
            )
        elif resolved_provider == "parallel":
            result = await self._search_parallel(
                query, num_results, self._provider_key(settings, "parallel")
            )
        else:
            return self._error(f"Unknown search provider '{resolved_provider}'.")

        if fallback_note and not result.startswith("Error"):
            return f"{fallback_note}\n\n{result}"
        return result

    @staticmethod
    def _is_configured_key(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())

    def _provider_key(self, settings: Any, provider: str) -> str | None:
        key_map = {
            "tavily": getattr(settings, "tavily_api_key", None),
            "brave": getattr(settings, "brave_search_api_key", None),
            "parallel": getattr(settings, "parallel_api_key", None),
        }
        value = key_map.get(provider)
        return value if self._is_configured_key(value) else None

    def _available_providers(self, settings: Any) -> list[str]:
        return [p for p in self._PROVIDER_PRIORITY if self._provider_key(settings, p)]

    @staticmethod
    def _missing_key_message(provider: str) -> str:
        if provider == "tavily":
            return (
                "Tavily API key not configured. "
                "Set POCKETPAW_TAVILY_API_KEY or switch to provider='auto'."
            )
        if provider == "brave":
            return (
                "Brave Search API key not configured. "
                "Set POCKETPAW_BRAVE_SEARCH_API_KEY or switch to provider='auto'."
            )
        if provider == "parallel":
            return (
                "Parallel AI API key not configured. "
                "Set POCKETPAW_PARALLEL_API_KEY or switch to provider='auto'."
            )
        return (
            f"{provider.title()} API key not configured. "
            "Set a search provider API key or use provider='auto'."
        )

    def _resolve_provider(
        self,
        settings: Any,
        provider_override: str | None,
    ) -> tuple[str, str | None, str | None]:
        requested = (provider_override or settings.web_search_provider or "auto").strip().lower()
        valid = set(self._PROVIDER_PRIORITY) | {"auto"}

        if requested not in valid:
            return "", None, (
                f"Unknown search provider '{requested}'. "
                "Use 'auto', 'tavily', 'brave', or 'parallel'."
            )

        available = self._available_providers(settings)

        if requested == "auto":
            if not available:
                return (
                    "",
                    None,
                    "No search API keys configured. "
                    "Set POCKETPAW_TAVILY_API_KEY, POCKETPAW_BRAVE_SEARCH_API_KEY, "
                    "or POCKETPAW_PARALLEL_API_KEY.",
                )
            return available[0], None, None

        if self._provider_key(settings, requested):
            return requested, None, None

        if available:
            fallback = available[0]
            note = (
                f"Note: Requested provider '{requested}' is not configured. "
                f"Falling back to '{fallback}'."
            )
            return fallback, note, None

        return (
            "",
            None,
            self._missing_key_message(requested),
        )

    async def _search_tavily(self, query: str, num_results: int, api_key: str | None) -> str:
        if not api_key:
            return self._error(
                "Tavily API key not configured. "
                "Set POCKETPAW_TAVILY_API_KEY or switch to 'brave' provider."
            )

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    _TAVILY_URL,
                    json={
                        "api_key": api_key,
                        "query": query,
                        "max_results": num_results,
                        "include_answer": False,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            results = data.get("results", [])
            if not results:
                return f"No results found for: {query}"

            return self._format_results(query, results[:num_results], "tavily")

        except httpx.HTTPStatusError as e:
            return self._error(f"Tavily API error: {e.response.status_code}")
        except Exception as e:
            return self._error(f"Search failed: {e}")

    async def _search_brave(self, query: str, num_results: int, api_key: str | None) -> str:
        if not api_key:
            return self._error(
                "Brave Search API key not configured. "
                "Set POCKETPAW_BRAVE_SEARCH_API_KEY or switch to 'tavily' provider."
            )

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    _BRAVE_URL,
                    params={"q": query, "count": num_results},
                    headers={
                        "X-Subscription-Token": api_key,
                        "Accept": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            web_results = data.get("web", {}).get("results", [])
            if not web_results:
                return f"No results found for: {query}"

            # Normalize Brave results to common format
            results = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("description", ""),
                }
                for r in web_results[:num_results]
            ]
            return self._format_results(query, results, "brave")

        except httpx.HTTPStatusError as e:
            return self._error(f"Brave API error: {e.response.status_code}")
        except Exception as e:
            return self._error(f"Search failed: {e}")

    async def _search_parallel(self, query: str, num_results: int, api_key: str | None) -> str:
        if not api_key:
            return self._error(
                "Parallel AI API key not configured. "
                "Set POCKETPAW_PARALLEL_API_KEY or switch to 'tavily'/'brave' provider."
            )

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    _PARALLEL_SEARCH_URL,
                    headers={
                        "x-api-key": api_key,
                        "parallel-beta": "search-extract-2025-10-10",
                        "Content-Type": "application/json",
                    },
                    json={
                        "search_queries": [query],
                        "max_results": num_results,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            results = data.get("results", [])
            if not results:
                return f"No results found for: {query}"

            # Normalize Parallel results to common format
            normalized = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": " ".join(r.get("excerpts", [])),
                }
                for r in results[:num_results]
            ]
            return self._format_results(query, normalized, "parallel")

        except httpx.HTTPStatusError as e:
            return self._error(f"Parallel AI API error: {e.response.status_code}")
        except Exception as e:
            return self._error(f"Search failed: {e}")

    def _format_results(self, query: str, results: list[dict], provider: str) -> str:
        provider_label = self._PROVIDER_LABELS.get(provider, provider.title())
        date_label = datetime.now().astimezone().strftime("%Y-%m-%d %I:%M %p")
        lines = [
            f"PocketPaw - Search {provider_label} - {date_label}",
            "",
            f"Search results for: {query}",
            "",
        ]
        for i, r in enumerate(results, 1):
            title = r.get("title", "Untitled")
            url = r.get("url", "")
            snippet = r.get("content", "")[:200]
            lines.append(f"{i}. **{title}**\n   {url}\n   {snippet}\n")
        return "\n".join(lines)

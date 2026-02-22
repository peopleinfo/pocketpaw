# Actor template base class.
"""Abstract base for actor templates (inspired by Apify actors).

Each actor defines an input schema (JSON Schema) that drives
a dynamic UI form, and a ``run()`` method that executes the scraping logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActorResult:
    """Result from running an actor template."""

    status: str  # "success" | "error" | "running"
    data: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    pages_crawled: int = 0
    items_extracted: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "data": self.data,
            "error": self.error,
            "pages_crawled": self.pages_crawled,
            "items_extracted": self.items_extracted,
        }


class ActorTemplate(ABC):
    """Base class for actor templates.

    Subclasses define:
    - ``id``, ``name``, ``icon``, ``description`` — metadata
    - ``input_schema`` — JSON Schema for the template's input form
    - ``run()`` — the actual scraping/automation logic
    """

    @property
    @abstractmethod
    def id(self) -> str:
        """Unique template identifier, e.g. 'web-scraper'."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Display name, e.g. 'Web Scraper'."""
        ...

    @property
    def icon(self) -> str:
        """Lucide icon name for the UI."""
        return "bot"

    @property
    def description(self) -> str:
        """Short description shown in template picker."""
        return ""

    @property
    def category(self) -> str:
        """Template category: 'scraper' | 'automation' | 'custom'."""
        return "scraper"

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema defining the template's configurable inputs.

        This drives the dynamic form in the UI. Example keys:
        startUrls, selectors, maxPages, linkSelector, etc.
        """
        ...

    @abstractmethod
    async def run(
        self,
        profile_fingerprint: dict[str, Any],
        plugin: str,
        inputs: dict[str, Any],
        user_data_dir: str | None = None,
        proxy: str | None = None,
    ) -> ActorResult:
        """Execute the actor template.

        Args:
            profile_fingerprint: Generated fingerprint dict.
            plugin: Browser plugin ID ('playwright' or 'camoufox').
            inputs: User-provided options matching input_schema.
            user_data_dir: Path for persistent browser data.
            proxy: Proxy URL if configured.

        Returns:
            ActorResult with extracted data or error.
        """
        ...

    def to_dict(self) -> dict[str, Any]:
        """Serialise for API responses."""
        return {
            "id": self.id,
            "name": self.name,
            "icon": self.icon,
            "description": self.description,
            "category": self.category,
            "input_schema": self.input_schema,
        }


__all__ = ["ActorTemplate", "ActorResult"]

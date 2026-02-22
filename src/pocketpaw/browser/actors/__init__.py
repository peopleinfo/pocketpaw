# Actor templates package — pre-built scraping recipes.
"""Actor template registry for anti-detect browser system.

Each actor template is a pre-built scraping recipe (like Apify's actors)
with its own input schema, run logic, and result format.
"""

from __future__ import annotations

import logging
from typing import Any

from pocketpaw.browser.actors.base import ActorTemplate

logger = logging.getLogger(__name__)

_ACTORS: dict[str, ActorTemplate] = {}


def register_actor(actor: ActorTemplate) -> None:
    """Register an actor template."""
    _ACTORS[actor.id] = actor
    logger.debug("Registered actor template: %s", actor.id)


def get_actor(actor_id: str) -> ActorTemplate | None:
    """Get an actor template by ID."""
    return _ACTORS.get(actor_id)


def list_actors() -> list[ActorTemplate]:
    """Return all registered actor templates."""
    return list(_ACTORS.values())


# ── Auto-register built-in actors ────────────────────────────────

def _auto_register() -> None:
    """Import and register all built-in actor templates."""
    from pocketpaw.browser.actors.web_scraper import WebScraperActor
    from pocketpaw.browser.actors.playwright_scraper import PlaywrightScraperActor
    from pocketpaw.browser.actors.custom_script import CustomScriptActor
    from pocketpaw.browser.actors.instagram_scraper import InstagramScraperActor

    register_actor(WebScraperActor())
    register_actor(PlaywrightScraperActor())
    register_actor(CustomScriptActor())
    register_actor(InstagramScraperActor())


_auto_register()

__all__ = ["ActorTemplate", "register_actor", "get_actor", "list_actors"]

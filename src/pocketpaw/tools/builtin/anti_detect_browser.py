"""Control the Anti-Detect Browser via the AI Agent."""

from __future__ import annotations

import json
from typing import Any

from pocketpaw.tools.protocol import BaseTool
from pocketpaw.browser.profile import get_profile_store
from pocketpaw.browser.actors import get_actor

class AntiDetectBrowserTool(BaseTool):
    """Tool for controlling the Anti-Detect Browser and running Web or Playwright Scrapers.
    
    This tool allows the agent to list available browser profiles, list available actor 
    templates, and optionally run an actor template using a specific profile.

    Actions:
        list_profiles: List all available browser profiles
        list_actors: List all available scraper actor templates
        run_actor: Run an actor template (like web-scraper) on a profile.
    """

    @property
    def name(self) -> str:
        return "anti_detect_browser"

    @property
    def description(self) -> str:
        return (
            "Control the Anti-Detect Browser subsystem. "
            "Use this tool to list available browser profiles, list available scraper "
            "actor templates, and run a scraper (e.g. web-scraper, playwright-scraper) "
            "with specific inputs (like start_urls and CSS selectors) using a profile's stealth fingerprint."
        )

    @property
    def trust_level(self) -> str:
        return "high"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "What to do: 'list_profiles', 'list_actors', or 'run_actor'",
                    "enum": ["list_profiles", "list_actors", "run_actor"],
                },
                "profile_id": {
                    "type": "string",
                    "description": "The ID of the browser profile to use (required for run_actor)",
                },
                "actor_id": {
                    "type": "string",
                    "description": "The ID of the actor template to run (e.g., 'web-scraper') (required for run_actor)",
                },
                "inputs": {
                    "type": "object",
                    "description": "Inputs for the actor. For web-scraper, this usually includes 'start_urls' (string with URLs separated by newlines) and 'selectors' (JSON string or dict mapping field names to CSS selectors).",
                },
            },
            "required": ["action"],
        }

    async def execute(self, **params: Any) -> str:
        action = params.get("action")

        try:
            if action == "list_profiles":
                return self._list_profiles()
            elif action == "list_actors":
                return self._list_actors()
            elif action == "run_actor":
                return await self._run_actor(params)
            else:
                return self._error(f"Unknown action: {action}")
        except Exception as e:
            return self._error(f"Anti-Detect Browser Tool Error: {str(e)}")

    def _list_profiles(self) -> str:
        store = get_profile_store()
        profiles = store.list()
        if not profiles:
            return "No anti-detect browser profiles found."
        
        lines = ["Available Profiles:"]
        for p in profiles:
            lines.append(f"- ID: {p.id} | Name: '{p.name}' | Status: {p.status} | Plugin: {p.plugin} | Browser: {p.browser_type}")
        return "\n".join(lines)

    def _list_actors(self) -> str:
        from pocketpaw.browser.actors import list_actors
        actors = list_actors()
        if not actors:
            return "No actor templates found."
        
        lines = ["Available Actor Templates:"]
        for a in actors:
            options = []
            for prop_name, prop_data in a.input_schema.get("properties", {}).items():
                options.append(f"{prop_name} ({prop_data.get('type')})")
            lines.append(f"- ID: {a.id} | Name: '{a.name}' | Inputs: {', '.join(options)}")
        return "\n".join(lines)

    async def _run_actor(self, params: dict[str, Any]) -> str:
        profile_id = params.get("profile_id")
        actor_id = params.get("actor_id")
        inputs = params.get("inputs", {})

        if not profile_id:
            return self._error("profile_id is required for run_actor")
        if not actor_id:
            return self._error("actor_id is required for run_actor")

        store = get_profile_store()
        profile = store.get(profile_id)
        if not profile:
            return self._error(f"Profile '{profile_id}' not found")

        actor = get_actor(actor_id)
        if not actor:
            return self._error(f"Actor '{actor_id}' not found")

        if profile.status == "RUNNING":
            return self._error(f"Profile '{profile_id}' is already running")

        store.set_status(profile_id, "RUNNING")

        try:
            result = await actor.run(
                profile_fingerprint=profile.fingerprint,
                plugin=profile.plugin,
                inputs=inputs,
                user_data_dir=profile.user_data_dir,
                proxy=profile.proxy
            )
            store.set_status(profile_id, "IDLE")

            if result.status == "error":
                return self._error(f"Actor failed: {result.error}")
            
            # Format the successful result
            summary = (
                f"Actor completed successfully. "
                f"Pages crawled: {result.pages_crawled}, Items extracted: {result.items_extracted}\n\n"
                f"Extracted Data:\n{json.dumps(result.data, indent=2)}"
            )
            # Truncate if massive
            if len(summary) > 5000:
                summary = summary[:5000] + "\n...[truncated output due to length]"
            return summary
        except Exception as e:
            store.set_status(profile_id, "ERROR")
            raise e

__all__ = ["AntiDetectBrowserTool"]

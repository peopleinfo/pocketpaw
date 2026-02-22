# Playwright Scraper actor template.
"""Playwright Scraper — full browser automation with custom page function.

Advanced actor for interacting with JS-heavy sites: clicking buttons,
filling forms, waiting for elements, extracting dynamic content.
"""

from __future__ import annotations

import logging
from typing import Any

from pocketpaw.browser.actors.base import ActorResult, ActorTemplate

logger = logging.getLogger(__name__)


class PlaywrightScraperActor(ActorTemplate):
    """Full browser automation with Playwright."""

    @property
    def id(self) -> str:
        return "playwright-scraper"

    @property
    def name(self) -> str:
        return "Playwright Scraper"

    @property
    def icon(self) -> str:
        return "drama"

    @property
    def description(self) -> str:
        return "Advanced browser automation. Interact with JS-heavy sites, click buttons, fill forms, and extract dynamic content."

    @property
    def category(self) -> str:
        return "automation"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "start_urls": {
                    "type": "string",
                    "title": "Start URLs",
                    "description": "URLs to automate (one per line)",
                    "ui:widget": "textarea",
                },
                "page_actions": {
                    "type": "string",
                    "title": "Page Actions (JSON)",
                    "description": 'List of actions: [{"action": "click", "selector": ".btn"}, {"action": "wait", "selector": ".result"}, {"action": "extract", "selector": ".data"}]',
                    "ui:widget": "textarea",
                    "default": '[]',
                },
                "screenshot": {
                    "type": "boolean",
                    "title": "Take Screenshot",
                    "description": "Capture a screenshot of each page after actions",
                    "default": False,
                },
                "wait_until": {
                    "type": "string",
                    "title": "Wait Until",
                    "description": "Page load event to wait for",
                    "enum": ["load", "domcontentloaded", "networkidle"],
                    "default": "load",
                },
                "timeout": {
                    "type": "integer",
                    "title": "Timeout (ms)",
                    "description": "Navigation timeout in milliseconds",
                    "default": 30000,
                    "minimum": 5000,
                    "maximum": 120000,
                },
            },
            "required": ["start_urls"],
        }

    async def run(
        self,
        profile_fingerprint: dict[str, Any],
        plugin: str,
        inputs: dict[str, Any],
        user_data_dir: str | None = None,
        proxy: str | None = None,
    ) -> ActorResult:
        """Run Playwright automation with page actions."""
        import json as json_module

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return ActorResult(status="error", error="Playwright not installed")

        start_urls_raw = inputs.get("start_urls", "")
        start_urls = [u.strip() for u in start_urls_raw.strip().split("\n") if u.strip()]

        if not start_urls:
            return ActorResult(status="error", error="No start URLs provided")

        # Parse page actions
        actions_raw = inputs.get("page_actions", "[]")
        try:
            actions = json_module.loads(actions_raw) if isinstance(actions_raw, str) else actions_raw
        except json_module.JSONDecodeError:
            return ActorResult(status="error", error="Invalid page actions JSON")

        wait_until = inputs.get("wait_until", "load")
        timeout = inputs.get("timeout", 30000)
        take_screenshot = inputs.get("screenshot", False)

        extracted_data: list[dict[str, Any]] = []

        async with async_playwright() as pw:
            # Launch with fingerprint
            if plugin == "camoufox":
                try:
                    from camoufox import AsyncNewBrowser
                    browser = await AsyncNewBrowser(pw, headless=True)
                except ImportError:
                    return ActorResult(status="error", error="Camoufox plugin requested but not installed")
            else:
                browser = await pw.chromium.launch(headless=True)

            context_opts: dict[str, Any] = {
                "user_agent": profile_fingerprint.get("user_agent", ""),
                "locale": profile_fingerprint.get("locale", "en-US"),
            }
            if profile_fingerprint.get("viewport"):
                context_opts["viewport"] = profile_fingerprint["viewport"]
            if proxy:
                context_opts["proxy"] = {"server": proxy}

            # Camoufox has its own fingerprinting, so we could technically skip some,
            # but setting context options is generally safe.
            context = await browser.new_context(**context_opts)
            page = await context.new_page()

            for url in start_urls:
                try:
                    await page.goto(url, wait_until=wait_until, timeout=timeout)

                    row: dict[str, Any] = {"url": url, "extracted": {}}

                    # Execute page actions
                    for action_def in actions:
                        action_type = action_def.get("action", "")
                        selector = action_def.get("selector", "")

                        if action_type == "click" and selector:
                            await page.click(selector, timeout=10000)
                        elif action_type == "wait" and selector:
                            await page.wait_for_selector(selector, timeout=10000)
                        elif action_type == "type" and selector:
                            text = action_def.get("text", "")
                            await page.fill(selector, text)
                        elif action_type == "extract" and selector:
                            field_name = action_def.get("field", selector)
                            el = await page.query_selector(selector)
                            row["extracted"][field_name] = await el.inner_text() if el else None
                        elif action_type == "scroll":
                            await page.evaluate("window.scrollBy(0, window.innerHeight)")
                        elif action_type == "delay":
                            import asyncio
                            await asyncio.sleep(action_def.get("ms", 1000) / 1000)

                    # Capture page title and content
                    row["title"] = await page.title()

                    if take_screenshot:
                        screenshot_bytes = await page.screenshot()
                        row["screenshot_size"] = len(screenshot_bytes)

                    extracted_data.append(row)

                except Exception as e:
                    logger.warning("Failed to automate %s: %s", url, e)
                    extracted_data.append({"url": url, "error": str(e)})

            await browser.close()

        return ActorResult(
            status="success",
            data=extracted_data,
            pages_crawled=len(extracted_data),
            items_extracted=sum(1 for d in extracted_data if "error" not in d),
        )


__all__ = ["PlaywrightScraperActor"]

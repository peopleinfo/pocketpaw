# Custom Script actor template.
"""Custom Script — run user-provided extraction logic.

Lets users write their own Python extraction code that runs
in the browser context with access to Playwright's page object.
"""

from __future__ import annotations

import logging
from typing import Any

from pocketpaw.browser.actors.base import ActorResult, ActorTemplate

logger = logging.getLogger(__name__)


class CustomScriptActor(ActorTemplate):
    """Run custom extraction logic on web pages."""

    @property
    def id(self) -> str:
        return "custom-script"

    @property
    def name(self) -> str:
        return "Custom Script"

    @property
    def icon(self) -> str:
        return "file-code"

    @property
    def description(self) -> str:
        return "Run custom JavaScript on pages to extract data. Full flexibility for complex extraction logic."

    @property
    def category(self) -> str:
        return "custom"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "start_urls": {
                    "type": "string",
                    "title": "Start URLs",
                    "description": "URLs to process (one per line)",
                    "ui:widget": "textarea",
                },
                "script": {
                    "type": "string",
                    "title": "JavaScript",
                    "description": "JavaScript to execute on each page. Use `return` to output data.",
                    "ui:widget": "code",
                    "default": "return { title: document.title, text: document.body.innerText.substring(0, 500) };",
                },
                "wait_for": {
                    "type": "string",
                    "title": "Wait For Selector",
                    "description": "CSS selector to wait for before running script",
                    "default": "",
                },
                "headless": {
                    "type": "boolean",
                    "title": "Headless",
                    "description": "Run browser in headless mode (no visible window)",
                    "default": True,
                },
            },
            "required": ["start_urls", "script"],
        }

    async def run(
        self,
        profile_fingerprint: dict[str, Any],
        plugin: str,
        inputs: dict[str, Any],
        user_data_dir: str | None = None,
        proxy: str | None = None,
    ) -> ActorResult:
        """Run custom JavaScript on each URL."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return ActorResult(status="error", error="Playwright not installed")

        start_urls_raw = inputs.get("start_urls", "")
        start_urls = [u.strip() for u in start_urls_raw.strip().split("\n") if u.strip()]

        if not start_urls:
            return ActorResult(status="error", error="No start URLs provided")

        script = inputs.get("script", "return { title: document.title };")
        wait_for = inputs.get("wait_for", "")
        headless = inputs.get("headless", True)

        # Wrap script in an IIFE if it doesn't start with function/return
        if not script.strip().startswith("(") and not script.strip().startswith("function"):
            script = f"() => {{ {script} }}"

        extracted_data: list[dict[str, Any]] = []

        async with async_playwright() as pw:
            if plugin == "camoufox":
                try:
                    from camoufox import AsyncNewBrowser
                    browser = await AsyncNewBrowser(pw, headless=headless)
                except ImportError:
                    return ActorResult(status="error", error="Camoufox plugin requested but not installed")
            else:
                browser = await pw.chromium.launch(headless=headless)

            context = await browser.new_context(
                user_agent=profile_fingerprint.get("user_agent", ""),
                viewport=profile_fingerprint.get("viewport"),
                locale=profile_fingerprint.get("locale", "en-US"),
            )
            page = await context.new_page()

            for url in start_urls:
                try:
                    await page.goto(url, timeout=30000)

                    if wait_for:
                        await page.wait_for_selector(wait_for, timeout=10000)

                    result = await page.evaluate(script)

                    row = {"url": url}
                    if isinstance(result, dict):
                        row.update(result)
                    else:
                        row["result"] = result

                    extracted_data.append(row)

                except Exception as e:
                    logger.warning("Script failed on %s: %s", url, e)
                    extracted_data.append({"url": url, "error": str(e)})

            await browser.close()

        return ActorResult(
            status="success",
            data=extracted_data,
            pages_crawled=len(extracted_data),
            items_extracted=sum(1 for d in extracted_data if "error" not in d),
        )


__all__ = ["CustomScriptActor"]

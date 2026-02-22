# Web Scraper actor template.
"""Web Scraper — crawl pages and extract data with CSS selectors.

Inspired by Apify's web-scraper actor. Uses Crawlee's PlaywrightCrawler
with fingerprint spoofing to crawl a list of URLs and extract structured
data using user-defined CSS selectors.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pocketpaw.browser.actors.base import ActorResult, ActorTemplate

logger = logging.getLogger(__name__)


class WebScraperActor(ActorTemplate):
    """Crawl pages and extract data using CSS selectors."""

    @property
    def id(self) -> str:
        return "web-scraper"

    @property
    def name(self) -> str:
        return "Web Scraper"

    @property
    def icon(self) -> str:
        return "globe"

    @property
    def description(self) -> str:
        return "Crawl web pages and extract structured data using CSS selectors. Great for product listings, article feeds, and directory pages."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "start_urls": {
                    "type": "string",
                    "title": "Start URLs",
                    "description": "URLs to start crawling (one per line)",
                    "ui:widget": "textarea",
                },
                "link_selector": {
                    "type": "string",
                    "title": "Link Selector",
                    "description": "CSS selector for links to follow (e.g. a.article-link)",
                    "default": "",
                },
                "selectors": {
                    "type": "string",
                    "title": "Data Selectors (JSON)",
                    "description": 'JSON object mapping field names to CSS selectors, e.g. {"title": "h1", "price": ".price"}',
                    "ui:widget": "textarea",
                    "default": '{"title": "h1", "content": "article"}',
                },
                "max_pages": {
                    "type": "integer",
                    "title": "Max Pages",
                    "description": "Maximum number of pages to crawl",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 1000,
                },
                "wait_for": {
                    "type": "string",
                    "title": "Wait For Selector",
                    "description": "CSS selector to wait for before extracting data",
                    "default": "",
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
        """Run the web scraper using Crawlee's PlaywrightCrawler."""
        import json as json_module

        start_urls_raw = inputs.get("start_urls", "")
        start_urls = [u.strip() for u in start_urls_raw.strip().split("\n") if u.strip()]

        if not start_urls:
            return ActorResult(status="error", error="No start URLs provided")

        # Parse selectors
        selectors_raw = inputs.get("selectors", '{"title": "h1"}')
        try:
            selectors = json_module.loads(selectors_raw) if isinstance(selectors_raw, str) else selectors_raw
        except json_module.JSONDecodeError:
            return ActorResult(status="error", error="Invalid selectors JSON")

        max_pages = inputs.get("max_pages", 10)
        link_selector = inputs.get("link_selector", "")
        wait_for = inputs.get("wait_for", "")

        try:
            return await self._run_crawlee(
                start_urls=start_urls,
                selectors=selectors,
                max_pages=max_pages,
                link_selector=link_selector,
                wait_for=wait_for,
                fingerprint=profile_fingerprint,
                plugin=plugin,
                proxy=proxy,
            )
        except ImportError:
            return await self._run_basic(
                start_urls=start_urls,
                selectors=selectors,
                fingerprint=profile_fingerprint,
            )

    async def _run_crawlee(
        self,
        start_urls: list[str],
        selectors: dict[str, str],
        max_pages: int,
        link_selector: str,
        wait_for: str,
        fingerprint: dict[str, Any],
        plugin: str,
        proxy: str | None,
    ) -> ActorResult:
        """Run with Crawlee's PlaywrightCrawler."""
        from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
        from crawlee.browser_pool import BrowserPool
        from crawlee.browsers import PlaywrightBrowserPlugin

        pool_plugins = []
        if plugin == "camoufox":
            try:
                from pocketpaw.browser.plugins.camoufox_plugin import CamoufoxPlugin
                pool_plugins.append(CamoufoxPlugin(browser_launch_options={"headless": True}))
            except ImportError:
                pool_plugins.append(PlaywrightBrowserPlugin(browser_type="chromium", browser_launch_options={"headless": True}))
        else:
            pool_plugins.append(PlaywrightBrowserPlugin(browser_type="chromium", browser_launch_options={"headless": True}))

        browser_pool = BrowserPool(plugins=pool_plugins)

        extracted_data: list[dict[str, Any]] = []
        pages_crawled = 0

        crawler = PlaywrightCrawler(
            max_requests_per_crawl=max_pages,
            browser_pool=browser_pool,
        )

        @crawler.router.default_handler
        async def handler(context: PlaywrightCrawlingContext) -> None:
            nonlocal pages_crawled
            pages_crawled += 1

            context.log.info(f"Scraping {context.request.url}")

            # Wait for specific selector if configured
            if wait_for:
                try:
                    await context.page.wait_for_selector(wait_for, timeout=10000)
                except Exception:
                    pass

            # Extract data using selectors
            row: dict[str, Any] = {"url": context.request.url}
            for field_name, selector in selectors.items():
                try:
                    el = await context.page.query_selector(selector)
                    if el:
                        row[field_name] = await el.inner_text()
                    else:
                        row[field_name] = None
                except Exception:
                    row[field_name] = None

            extracted_data.append(row)

            # Follow links if configured
            if link_selector:
                await context.enqueue_links(selector=link_selector)

        await crawler.run(start_urls)

        return ActorResult(
            status="success",
            data=extracted_data,
            pages_crawled=pages_crawled,
            items_extracted=len(extracted_data),
        )

    async def _run_basic(
        self,
        start_urls: list[str],
        selectors: dict[str, str],
        fingerprint: dict[str, Any],
    ) -> ActorResult:
        """Basic fallback using Playwright directly (no Crawlee)."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return ActorResult(status="error", error="Playwright not installed")

        extracted_data: list[dict[str, Any]] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=fingerprint.get("user_agent", ""),
                viewport=fingerprint.get("viewport"),
                locale=fingerprint.get("locale", "en-US"),
            )
            page = await context.new_page()

            for url in start_urls[:10]:  # Limit in fallback mode
                try:
                    await page.goto(url, timeout=30000)
                    row: dict[str, Any] = {"url": url}
                    for field_name, selector in selectors.items():
                        try:
                            el = await page.query_selector(selector)
                            row[field_name] = await el.inner_text() if el else None
                        except Exception:
                            row[field_name] = None
                    extracted_data.append(row)
                except Exception as e:
                    logger.warning("Failed to scrape %s: %s", url, e)

            await browser.close()

        return ActorResult(
            status="success",
            data=extracted_data,
            pages_crawled=len(extracted_data),
            items_extracted=len(extracted_data),
        )


__all__ = ["WebScraperActor"]

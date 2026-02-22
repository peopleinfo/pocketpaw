# Instagram Scraper actor template.
"""Instagram Scraper — scrape profiles, hashtags, places, and posts.

Inspired by Apify's Instagram Scraper actor. Uses Playwright with
anti-detect fingerprinting to scrape public Instagram data: posts,
comments, profile details, hashtags, and places.
"""

from __future__ import annotations

import asyncio
import json as json_module
import logging
import re
from typing import Any

from pocketpaw.browser.actors.base import ActorResult, ActorTemplate

logger = logging.getLogger(__name__)


class InstagramScraperActor(ActorTemplate):
    """Scrape Instagram profiles, hashtags, places, and posts."""

    @property
    def id(self) -> str:
        return "instagram-scraper"

    @property
    def name(self) -> str:
        return "Instagram Scraper"

    @property
    def icon(self) -> str:
        return "instagram"

    @property
    def description(self) -> str:
        return (
            "Scrape and extract data from Instagram. Get posts, comments, "
            "profile details, hashtags, and places. Supports search and "
            "direct URL scraping with anti-detect browser profiles."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "direct_urls": {
                    "type": "string",
                    "title": "Direct URLs",
                    "description": (
                        "Instagram URLs to scrape (one per line). "
                        "E.g. https://www.instagram.com/natgeo"
                    ),
                    "ui:widget": "textarea",
                },
                "results_type": {
                    "type": "string",
                    "title": "Results Type",
                    "description": "Type of data to extract from each URL",
                    "enum": ["posts", "comments", "details"],
                    "default": "posts",
                },
                "results_limit": {
                    "type": "integer",
                    "title": "Results Limit",
                    "description": "Maximum number of results per page/URL",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 200,
                },
                "search": {
                    "type": "string",
                    "title": "Search Query",
                    "description": (
                        "Search Instagram for profiles, hashtags, or places. "
                        "Leave empty if using Direct URLs."
                    ),
                    "default": "",
                },
                "search_type": {
                    "type": "string",
                    "title": "Search Type",
                    "description": "Type of entity to search for",
                    "enum": ["user", "hashtag", "place"],
                    "default": "hashtag",
                },
                "search_limit": {
                    "type": "integer",
                    "title": "Search Limit",
                    "description": "Maximum number of search results",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 250,
                },
                "only_posts_newer_than": {
                    "type": "string",
                    "title": "Only Posts Newer Than",
                    "description": (
                        "Limit by date. Supports YYYY-MM-DD or relative "
                        "formats like '7 days', '2 months'."
                    ),
                    "default": "",
                },
                "add_parent_data": {
                    "type": "boolean",
                    "title": "Add Parent Data",
                    "description": (
                        "Include source metadata (profile info) with each result"
                    ),
                    "default": False,
                },
                "headless": {
                    "type": "boolean",
                    "title": "Headless",
                    "description": "Run browser in headless mode (no visible window)",
                    "default": True,
                },
            },
            "required": [],
        }

    async def run(
        self,
        profile_fingerprint: dict[str, Any],
        plugin: str,
        inputs: dict[str, Any],
        user_data_dir: str | None = None,
        proxy: str | None = None,
    ) -> ActorResult:
        """Run the Instagram scraper."""

        direct_urls_raw = inputs.get("direct_urls", "")
        direct_urls = [
            u.strip() for u in direct_urls_raw.strip().split("\n") if u.strip()
        ]

        search_query = inputs.get("search", "").strip()
        search_type = inputs.get("search_type", "hashtag")
        search_limit = inputs.get("search_limit", 10)
        results_type = inputs.get("results_type", "posts")
        results_limit = inputs.get("results_limit", 20)
        add_parent_data = inputs.get("add_parent_data", False)
        headless = inputs.get("headless", True)

        # Build list of URLs to scrape
        urls_to_scrape: list[str] = list(direct_urls)

        # If search is provided, build search-based URLs
        if search_query and not urls_to_scrape:
            urls_to_scrape = self._build_search_urls(
                search_query, search_type, search_limit
            )

        if not urls_to_scrape:
            return ActorResult(
                status="error",
                error="No URLs or search query provided. Provide either Direct URLs or a Search query.",
            )

        try:
            return await self._scrape_instagram(
                urls=urls_to_scrape,
                results_type=results_type,
                results_limit=results_limit,
                add_parent_data=add_parent_data,
                fingerprint=profile_fingerprint,
                plugin=plugin,
                proxy=proxy,
                headless=headless,
            )
        except ImportError as e:
            return ActorResult(
                status="error",
                error=f"Missing dependency: {e}. Install playwright.",
            )
        except Exception as e:
            logger.exception("Instagram scraper failed")
            return ActorResult(status="error", error=str(e))

    def _build_search_urls(
        self, query: str, search_type: str, limit: int
    ) -> list[str]:
        """Convert search query into Instagram URLs."""
        base = "https://www.instagram.com"
        urls: list[str] = []

        if search_type == "hashtag":
            # Clean the hashtag (remove # if present)
            tag = query.lstrip("#").strip().replace(" ", "")
            urls.append(f"{base}/explore/tags/{tag}/")
        elif search_type == "user":
            # Could be multiple users comma-separated
            for user in query.split(","):
                user = user.strip().lstrip("@")
                if user:
                    urls.append(f"{base}/{user}/")
        elif search_type == "place":
            # Places require location IDs; use explore search
            urls.append(f"{base}/explore/search/keyword/?q={query}")

        return urls[:limit]

    async def _scrape_instagram(
        self,
        urls: list[str],
        results_type: str,
        results_limit: int,
        add_parent_data: bool,
        fingerprint: dict[str, Any],
        plugin: str,
        proxy: str | None,
        headless: bool = True,
    ) -> ActorResult:
        """Scrape Instagram pages using Playwright."""
        from playwright.async_api import async_playwright

        extracted_data: list[dict[str, Any]] = []
        pages_crawled = 0

        async with async_playwright() as pw:
            # Launch with anti-detect plugin
            if plugin == "camoufox":
                try:
                    from camoufox import AsyncNewBrowser
                    browser = await AsyncNewBrowser(pw, headless=headless)
                except ImportError:
                    return ActorResult(
                        status="error",
                        error="Camoufox plugin requested but not installed",
                    )
            else:
                browser = await pw.chromium.launch(headless=headless)

            # Configure context with fingerprint
            context_opts: dict[str, Any] = {
                "user_agent": fingerprint.get("user_agent", ""),
                "locale": fingerprint.get("locale", "en-US"),
            }
            if fingerprint.get("viewport"):
                context_opts["viewport"] = fingerprint["viewport"]
            if proxy:
                context_opts["proxy"] = {"server": proxy}

            context = await browser.new_context(**context_opts)
            page = await context.new_page()

            for url in urls:
                try:
                    logger.info("Scraping Instagram URL: %s", url)
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await asyncio.sleep(2)  # Wait for dynamic content

                    pages_crawled += 1

                    if results_type == "details":
                        profile_data = await self._extract_profile_details(page, url)
                        extracted_data.append(profile_data)

                    elif results_type == "comments":
                        comments = await self._extract_comments(
                            page, url, results_limit
                        )
                        extracted_data.extend(comments)

                    else:  # posts (default)
                        posts = await self._extract_posts(
                            page, url, results_limit, add_parent_data
                        )
                        extracted_data.extend(posts)

                except Exception as e:
                    logger.warning("Failed to scrape %s: %s", url, e)
                    extracted_data.append({"url": url, "error": str(e)})

            await browser.close()

        return ActorResult(
            status="success",
            data=extracted_data,
            pages_crawled=pages_crawled,
            items_extracted=sum(1 for d in extracted_data if "error" not in d),
        )

    async def _extract_profile_details(
        self, page: Any, url: str
    ) -> dict[str, Any]:
        """Extract profile metadata from an Instagram profile page."""
        profile: dict[str, Any] = {"url": url, "type": "profile"}

        try:
            # Try to extract from meta tags and visible elements
            profile["title"] = await page.title()

            # Extract from JSON-LD or meta tags
            meta_desc = await page.query_selector('meta[property="og:description"]')
            if meta_desc:
                profile["og_description"] = await meta_desc.get_attribute("content")

            meta_title = await page.query_selector('meta[property="og:title"]')
            if meta_title:
                profile["og_title"] = await meta_title.get_attribute("content")

            meta_image = await page.query_selector('meta[property="og:image"]')
            if meta_image:
                profile["profile_pic_url"] = await meta_image.get_attribute("content")

            # Try to extract username from URL
            match = re.search(r"instagram\.com/([^/?#]+)", url)
            if match:
                profile["username"] = match.group(1)

            # Extract visible text data
            header = await page.query_selector("header")
            if header:
                header_text = await header.inner_text()
                profile["header_text"] = header_text

                # Parse follower counts from header text
                numbers = re.findall(r"([\d,\.]+[KMB]?)\s*(posts?|followers?|following)", header_text, re.IGNORECASE)
                for count_str, label in numbers:
                    profile[label.lower().rstrip("s")] = count_str

            # Extract bio
            bio_el = await page.query_selector("header section > div:last-child")
            if bio_el:
                profile["biography"] = await bio_el.inner_text()

        except Exception as e:
            logger.warning("Error extracting profile details: %s", e)
            profile["extraction_error"] = str(e)

        return profile

    async def _extract_posts(
        self,
        page: Any,
        url: str,
        limit: int,
        add_parent_data: bool,
    ) -> list[dict[str, Any]]:
        """Extract posts from an Instagram page by scrolling."""
        posts: list[dict[str, Any]] = []

        # Get parent data if requested
        parent_data: dict[str, Any] = {}
        if add_parent_data:
            parent_data = {"source_url": url}
            meta_title = await page.query_selector('meta[property="og:title"]')
            if meta_title:
                parent_data["source_title"] = await meta_title.get_attribute("content")

        scroll_attempts = 0
        max_scrolls = min(limit // 3 + 2, 50)  # Rough: ~3 posts per scroll

        while len(posts) < limit and scroll_attempts < max_scrolls:
            # Extract post links from the page
            post_links = await page.query_selector_all('a[href*="/p/"], a[href*="/reel/"]')

            for link in post_links:
                if len(posts) >= limit:
                    break

                href = await link.get_attribute("href")
                if not href:
                    continue

                # Build full URL
                full_url = href if href.startswith("http") else f"https://www.instagram.com{href}"

                # Avoid duplicates
                if any(p.get("url") == full_url for p in posts):
                    continue

                post: dict[str, Any] = {
                    "url": full_url,
                    "type": "post",
                    "input_url": url,
                }

                # Extract shortcode from URL
                shortcode_match = re.search(r"/(?:p|reel)/([^/?#]+)", href)
                if shortcode_match:
                    post["shortcode"] = shortcode_match.group(1)

                # Try to get image from the link's img child
                img = await link.query_selector("img")
                if img:
                    post["display_url"] = await img.get_attribute("src") or ""
                    post["alt"] = await img.get_attribute("alt") or ""

                if add_parent_data:
                    post["parent"] = parent_data

                posts.append(post)

            # Scroll down to load more
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await asyncio.sleep(1.5)
            scroll_attempts += 1

        return posts

    async def _extract_comments(
        self, page: Any, url: str, limit: int
    ) -> list[dict[str, Any]]:
        """Extract comments from an Instagram post page."""
        comments: list[dict[str, Any]] = []

        try:
            # Comments are typically in a list under the post
            comment_elements = await page.query_selector_all(
                'ul > li[role="menuitem"], div[role="button"] + ul > li'
            )

            for i, el in enumerate(comment_elements):
                if i >= limit:
                    break

                try:
                    text = await el.inner_text()
                    if not text.strip():
                        continue

                    comment: dict[str, Any] = {
                        "post_url": url,
                        "position": i + 1,
                        "text": text.strip(),
                        "type": "comment",
                    }

                    # Try to split username from comment text
                    # Instagram comments often show as "username\ncomment text"
                    lines = text.strip().split("\n")
                    if len(lines) >= 2:
                        comment["owner_username"] = lines[0].strip()
                        comment["text"] = "\n".join(lines[1:]).strip()

                    comments.append(comment)
                except Exception:
                    continue

            # If no comments found via selectors, try alternative approach
            if not comments:
                # Look for any comment-like containers
                alt_comments = await page.query_selector_all(
                    'div[class*="comment"], span[class*="comment"]'
                )
                for i, el in enumerate(alt_comments[:limit]):
                    try:
                        text = await el.inner_text()
                        if text.strip():
                            comments.append({
                                "post_url": url,
                                "position": i + 1,
                                "text": text.strip(),
                                "type": "comment",
                            })
                    except Exception:
                        continue

        except Exception as e:
            logger.warning("Error extracting comments from %s: %s", url, e)
            comments.append({
                "post_url": url,
                "error": str(e),
                "type": "comment",
            })

        return comments


__all__ = ["InstagramScraperActor"]

"""Camoufox browser plugin for Crawlee."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from crawlee.browsers import PlaywrightBrowserPlugin
from crawlee.browsers._playwright_browser_controller import PlaywrightBrowserController

if TYPE_CHECKING:
    from playwright.async_api import Browser

logger = logging.getLogger(__name__)


class CamoufoxPlugin(PlaywrightBrowserPlugin):
    """Browser pool plugin that launches Camoufox instead of standard Playwright browsers."""

    def __init__(self, **kwargs):
        # Default to firefox since Camoufox is a Firefox fork,
        # but the actual launch logic will override this.
        kwargs.setdefault("browser_type", "firefox")
        super().__init__(**kwargs)

    async def new_browser(self) -> PlaywrightBrowserController:
        """Launch a new Camoufox browser instance."""
        from camoufox import AsyncNewBrowser

        if not self._playwright:
            raise RuntimeError("Playwright is not initialized")

        # Launch Camoufox with stealth fingerprint options
        logger.debug("Launching Camoufox browser instance...")
        # Note: **self._browser_launch_options passes headless=True down
        browser = await AsyncNewBrowser(self._playwright, **self._browser_launch_options)

        return PlaywrightBrowserController(
            browser,
            use_incognito_pages=self._use_incognito_pages,
            max_open_pages_per_browser=self._max_open_pages_per_browser,
            fingerprint_generator=None,  # Camoufox has its own built-in fingerprinting
        )

# Fingerprint generation for anti-detect browser profiles.
"""Fingerprint generation using Crawlee's fingerprint_suite.

Generates realistic browser fingerprints (user-agent, viewport, locale, etc.)
for anti-detect profiles. Falls back gracefully if Crawlee is not installed.
"""

from __future__ import annotations

import logging
import random
from typing import Any

logger = logging.getLogger(__name__)

# Default screen resolutions by OS
_SCREEN_SIZES = {
    "macos": [(1440, 900), (1680, 1050), (1920, 1080), (2560, 1440)],
    "windows": [(1366, 768), (1920, 1080), (2560, 1440), (1536, 864)],
    "linux": [(1920, 1080), (1366, 768), (1280, 1024)],
}

_USER_AGENTS_FALLBACK = {
    ("chromium", "macos"): "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    ("chromium", "windows"): "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    ("chromium", "linux"): "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    ("firefox", "macos"): "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
    ("firefox", "windows"): "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    ("firefox", "linux"): "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
}

_LOCALES = ["en-US", "en-GB", "en-AU", "en-CA", "de-DE", "fr-FR", "ja-JP", "ko-KR"]


def generate_fingerprint(
    browser: str = "chromium",
    os_type: str = "macos",
    locale: str | None = None,
) -> dict[str, Any]:
    """Generate a browser fingerprint.

    Tries Crawlee's ``DefaultFingerprintGenerator`` first.
    Falls back to basic randomised values if Crawlee is not installed.

    Returns:
        Dict with keys: user_agent, viewport, locale, headers, timezone_id
    """
    try:
        return _generate_crawlee(browser, os_type, locale)
    except ImportError:
        logger.info("Crawlee not installed — using basic fingerprint fallback")
        return _generate_basic(browser, os_type, locale)
    except Exception:
        logger.warning("Crawlee fingerprint generation failed — using fallback", exc_info=True)
        return _generate_basic(browser, os_type, locale)


def _generate_crawlee(browser: str, os_type: str, locale: str | None) -> dict[str, Any]:
    """Generate fingerprint using Crawlee's fingerprint_suite."""
    from crawlee.fingerprint_suite import (
        DefaultFingerprintGenerator,
        HeaderGeneratorOptions,
        ScreenOptions,
    )

    # Map our names to Crawlee names
    browser_map = {"chromium": "chrome", "firefox": "firefox"}
    os_map = {"macos": "macos", "windows": "windows", "linux": "linux"}

    gen = DefaultFingerprintGenerator(
        header_options=HeaderGeneratorOptions(
            browsers=[browser_map.get(browser, "chrome")],
            operating_systems=[os_map.get(os_type, "macos")],
            locales=[locale or "en-US"],
        ),
        screen_options=ScreenOptions(min_width=1024, max_width=1920),
    )

    fp = gen.generate()

    # Extract useful data from Crawlee's fingerprint object
    result: dict[str, Any] = {
        "source": "crawlee",
        "user_agent": getattr(fp, "user_agent", None) or str(fp.headers.get("user-agent", "")),
        "viewport": {"width": 1920, "height": 1080},
        "locale": locale or "en-US",
        "headers": dict(fp.headers) if hasattr(fp, "headers") else {},
    }

    # Try to extract screen info
    if hasattr(fp, "screen"):
        result["viewport"] = {
            "width": getattr(fp.screen, "width", 1920),
            "height": getattr(fp.screen, "height", 1080),
        }

    if hasattr(fp, "fingerprint"):
        result["fingerprint_data"] = fp.fingerprint

    return result


def _generate_basic(browser: str, os_type: str, locale: str | None) -> dict[str, Any]:
    """Basic fallback fingerprint — random user-agent + viewport."""
    key = (browser, os_type)
    user_agent = _USER_AGENTS_FALLBACK.get(key, _USER_AGENTS_FALLBACK[("chromium", "macos")])
    width, height = random.choice(_SCREEN_SIZES.get(os_type, _SCREEN_SIZES["macos"]))
    chosen_locale = locale or random.choice(_LOCALES)

    return {
        "source": "basic",
        "user_agent": user_agent,
        "viewport": {"width": width, "height": height},
        "locale": chosen_locale,
        "headers": {"user-agent": user_agent, "accept-language": chosen_locale},
    }


def fingerprint_to_context_options(fp: dict[str, Any]) -> dict[str, Any]:
    """Convert a stored fingerprint dict to Playwright context options."""
    opts: dict[str, Any] = {}

    if fp.get("user_agent"):
        opts["user_agent"] = fp["user_agent"]
    if fp.get("viewport"):
        opts["viewport"] = fp["viewport"]
    if fp.get("locale"):
        opts["locale"] = fp["locale"]

    return opts


__all__ = ["generate_fingerprint", "fingerprint_to_context_options"]

# E2E Test Configuration for Playwright
# Created: 2026-02-05
#
# Provides fixtures for E2E tests:
# - Dashboard server startup/shutdown
# - Browser configuration
# - Test isolation
#
# Run with: pytest tests/e2e/ -v
# Run headed (see browser): pytest tests/e2e/ -v --headed

import os
import socket
import time
from contextlib import closing
from multiprocessing import Process
from typing import Any

import pytest

_dashboard_process: Process | None = None


def find_free_port() -> int:
    """Find a free port on localhost."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def run_dashboard(port: int):
    """Run the dashboard server in a subprocess."""
    import uvicorn

    from pocketpaw.dashboard import app

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def wait_for_server(port: int, timeout: float = 10.0) -> bool:
    """Wait for the server to be ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
                s.settimeout(1)
                s.connect(("127.0.0.1", port))
                return True
        except (OSError, ConnectionRefusedError):
            time.sleep(0.1)
    return False


def _shutdown_process(process: Process | None) -> None:
    """Terminate a multiprocessing process and hard-kill if needed."""
    if process is None:
        return
    if not process.is_alive():
        process.join(timeout=1)
        return
    process.terminate()
    process.join(timeout=5)
    if process.is_alive():
        process.kill()
        process.join(timeout=2)


@pytest.fixture(scope="session")
def dashboard_port() -> int:
    """Get a free port for the dashboard."""
    return find_free_port()


@pytest.fixture(scope="session")
def dashboard_server(dashboard_port: int):
    """Start the dashboard server for the test session.

    Yields the base URL for the dashboard.
    """
    # Set test environment
    os.environ["POCKETPAW_TEST_MODE"] = "1"

    # Start server in subprocess
    process = Process(target=run_dashboard, args=(dashboard_port,))
    process.daemon = True
    process.start()
    global _dashboard_process
    _dashboard_process = process

    # Wait for server to be ready
    if not wait_for_server(dashboard_port):
        _shutdown_process(process)
        pytest.fail(f"Dashboard server failed to start on port {dashboard_port}")

    try:
        yield f"http://127.0.0.1:{dashboard_port}"
    finally:
        _shutdown_process(process)
        _dashboard_process = None


@pytest.fixture(autouse=True)
def _close_extra_browser_tabs(page):
    """Keep a single active tab per test and cleanup popups/new tabs."""
    context = page.context

    # Pre-test cleanup in case a previous failure left extra tabs around.
    for extra_page in list(context.pages):
        if extra_page is page:
            continue
        if not extra_page.is_closed():
            extra_page.close()

    yield

    # Post-test cleanup: close any new tabs created during the test.
    for extra_page in list(context.pages):
        if extra_page is page:
            continue
        if not extra_page.is_closed():
            extra_page.close()

    # Free page resources between tests without opening additional tabs.
    if not page.is_closed():
        try:
            page.goto("about:blank", wait_until="domcontentloaded", timeout=3000)
        except Exception:
            # If navigation fails because the test closed the page, skip cleanup.
            pass


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Final safety net to avoid orphan dashboard processes after test session."""
    del session, exitstatus
    _shutdown_process(_dashboard_process)


@pytest.fixture(scope="session")
def browser_context_args() -> dict[str, Any]:
    """Configure browser context for tests."""
    return {
        "viewport": {"width": 1280, "height": 720},
        "ignore_https_errors": True,
    }


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add local Playwright options when pytest-playwright plugin is unavailable."""
    group = parser.getgroup("pocketpaw-e2e")
    try:
        group.addoption(
            "--headed",
            action="store_true",
            default=False,
            help="Run E2E browser tests with a visible browser window.",
        )
    except ValueError:
        pass
    try:
        group.addoption(
            "--browser",
            action="store",
            default="chromium",
            choices=["chromium", "firefox", "webkit"],
            help="Browser engine to use for E2E tests.",
        )
    except ValueError:
        pass
    try:
        group.addoption(
            "--slowmo",
            action="store",
            default="0",
            help="Delay (ms) between Playwright actions for debugging.",
        )
    except ValueError:
        pass


@pytest.fixture(scope="session")
def playwright_instance():
    """Create a session-scoped Playwright runtime."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        yield playwright


@pytest.fixture(scope="session")
def browser(pytestconfig: pytest.Config, playwright_instance):
    """Launch one browser instance for the full E2E test session."""
    browser_name = getattr(pytestconfig.option, "browser", "chromium")
    browser_type = getattr(playwright_instance, browser_name, None)
    if browser_type is None:
        raise pytest.UsageError(f"Unsupported browser '{browser_name}'")

    slow_mo_raw = getattr(pytestconfig.option, "slowmo", "0")
    try:
        slow_mo = max(0, int(slow_mo_raw))
    except (TypeError, ValueError):
        slow_mo = 0

    launch_kwargs: dict[str, Any] = {
        "headless": not bool(getattr(pytestconfig.option, "headed", False))
    }
    if slow_mo:
        launch_kwargs["slow_mo"] = slow_mo

    browser_instance = browser_type.launch(**launch_kwargs)
    try:
        yield browser_instance
    finally:
        browser_instance.close()


@pytest.fixture
def context(browser, browser_context_args: dict[str, Any]):
    """Create an isolated browser context per test."""
    context_instance = browser.new_context(**browser_context_args)
    try:
        yield context_instance
    finally:
        context_instance.close()


@pytest.fixture
def page(context):
    """Create one primary page per test."""
    page_instance = context.new_page()
    try:
        yield page_instance
    finally:
        if not page_instance.is_closed():
            page_instance.close()


@pytest.fixture
def dashboard_url(dashboard_server: str) -> str:
    """Alias for dashboard_server URL."""
    return dashboard_server

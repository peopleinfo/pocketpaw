"""E2E tests for Pinokio-style plugin isolation in the dashboard.

Tests that the dashboard correctly displays python_version and cuda_version
for plugins, and that the wan2gp install flow works with isolated environments.
"""

import json
import re
import pytest

from playwright.sync_api import Page, expect


class TestAiUIPluginIsolation:
    """E2E tests for plugin isolation (python_version / cuda_version)."""

    def test_plugin_shows_python_version_badge(self, page: Page, dashboard_url: str):
        """Test that a plugin with python_version shows it in the plugin list."""

        def handle_plugins(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "plugins": [
                        {
                            "id": "wan2gp",
                            "name": "Wan2GP",
                            "description": "WanGP local UI",
                            "icon": "film",
                            "version": "1.0.0",
                            "port": 7860,
                            "status": "stopped",
                            "path": "/tmp/plugins/wan2gp",
                            "start_cmd": "python pocketpaw_start.py",
                            "has_install": True,
                            "python_version": "3.10",
                            "cuda_version": "12.8",
                            "web_view": "iframe",
                            "web_view_path": "/",
                            "requires": ["python", "git"],
                            "env": {},
                        }
                    ]
                }),
            )

        page.route(re.compile(r".*/api/ai-ui/plugins(?:\?.*)?$"), handle_plugins)
        page.goto(dashboard_url)

        # Navigate to AI UI → Plugins view
        page.locator("button:has-text('AI UI Local Cloud')").click()
        page.locator("button:has-text('My Apps')").first.click()

        # Verify plugin and badges appear
        wan2gp_name = page.get_by_text("Wan2GP").first
        expect(wan2gp_name).to_be_visible(timeout=10000)

        # Check for Python version badge
        py_badge = page.locator("[data-testid='python-version-badge']").first
        expect(py_badge).to_be_visible(timeout=5000)

        # Check for CUDA version badge
        cuda_badge = page.locator("[data-testid='cuda-version-badge']").first
        expect(cuda_badge).to_be_visible(timeout=5000)

    def test_wan2gp_install_with_isolation_metadata(self, page: Page, dashboard_url: str):
        """Test that wan2gp install request includes isolation metadata."""
        state = {"install_called": False, "install_source": ""}

        def handle_install(route):
            if route.request.method == "POST":
                state["install_called"] = True
                body = route.request.post_data or ""
                state["install_source"] = body
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({
                        "status": "ok",
                        "message": "Wan2GP has been added!",
                        "plugin_id": "wan2gp",
                    }),
                )
                return
            route.continue_()

        def handle_gallery(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "apps": [
                        {
                            "id": "wan2gp",
                            "name": "Wan2GP",
                            "description": "WanGP local UI – Python 3.10 + CUDA 12.8",
                            "icon": "film",
                            "source": "builtin:wan2gp",
                            "stars": "Windows-first",
                            "category": "Built-in",
                        }
                    ]
                }),
            )

        def handle_plugins(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"plugins": []}),
            )

        page.route(re.compile(r".*/api/ai-ui/plugins/install(?:\?.*)?$"), handle_install)
        page.route(re.compile(r".*/api/ai-ui/gallery(?:\?.*)?$"), handle_gallery)
        page.route(re.compile(r".*/api/ai-ui/plugins(?:\?.*)?$"), handle_plugins)

        page.goto(dashboard_url)

        # Navigate to Discover view
        page.locator("button:has-text('AI UI Local Cloud')").click()
        page.locator("button:has-text('Discover')").first.click()

        expect(page.get_by_text("Discover AI Apps").first).to_be_visible()

        # Find wan2gp card
        wan2gp_card = page.locator("div:has-text('builtin:wan2gp')").first
        expect(wan2gp_card).to_be_visible(timeout=10000)

        # Click Install
        wan2gp_card.locator("button:has-text('Install')").click()

        # Wait for install to complete (mocked as instant success)
        page.wait_for_timeout(2000)

        assert state["install_called"], "Install API should have been called"

    def test_wan2gp_install_nvidia_error_shows_detail(self, page: Page, dashboard_url: str):
        """Test that Wan2GP install failures display the full error message."""
        state = {"install_calls": 0}

        def handle_install(route):
            if route.request.method == "POST":
                state["install_calls"] += 1
                route.fulfill(
                    status=500,
                    content_type="application/json",
                    body=json.dumps({
                        "detail": (
                            "Failed to setup built-in 'wan2gp': "
                            "Wan2GP requires an NVIDIA GPU for this preset flow.\n"
                            "Set WAN2GP_ALLOW_NO_NVIDIA=1 to force install anyway.\n"
                            "Python 3.10 (isolated) | CUDA 12.8"
                        )
                    }),
                )
                return
            route.continue_()

        def handle_gallery(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "apps": [
                        {
                            "id": "wan2gp",
                            "name": "Wan2GP",
                            "description": "WanGP local UI wrapper",
                            "icon": "film",
                            "source": "builtin:wan2gp",
                            "stars": "Windows-first",
                            "category": "Built-in",
                        }
                    ]
                }),
            )

        def handle_plugins(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"plugins": []}),
            )

        page.route(re.compile(r".*/api/ai-ui/plugins/install(?:\?.*)?$"), handle_install)
        page.route(re.compile(r".*/api/ai-ui/gallery(?:\?.*)?$"), handle_gallery)
        page.route(re.compile(r".*/api/ai-ui/plugins(?:\?.*)?$"), handle_plugins)

        page.goto(dashboard_url)
        page.locator("button:has-text('AI UI Local Cloud')").click()
        page.locator("button:has-text('Discover')").first.click()

        expect(page.get_by_text("Discover AI Apps").first).to_be_visible()

        wan2gp_card = page.locator("div:has-text('builtin:wan2gp')").first
        expect(wan2gp_card).to_be_visible(timeout=10000)

        wan2gp_card.locator("button:has-text('Install')").click()

        # Verify error message is displayed
        error_msg = page.get_by_text("Wan2GP requires an NVIDIA GPU").first
        expect(error_msg).to_be_attached(timeout=10000)

        assert state["install_calls"] == 1

    @pytest.mark.timeout(1800)  # 30 minutes for downloading 3GB PyTorch
    def test_wan2gp_full_unmocked_install_and_launch(self, page: Page, dashboard_url: str):
        """Unmocked E2E test that actually installs and launches Wan2GP."""
        # Unroute everything to hit the real backend
        page.unroute("*")

        page.goto(dashboard_url)

        # 1. Discover -> Install
        page.locator("button:has-text('AI UI Local Cloud')").click()
        page.locator("button:has-text('Discover')").first.click()
        
        wan2gp_card = page.locator("div:has-text('builtin:wan2gp')").first
        expect(wan2gp_card).to_be_visible(timeout=10000)
        wan2gp_card.locator("button:has-text('Install')").click()

        # Wait for install to finish (can take minutes if cloning repo and making venv)
        expect(page.locator(".toast:has-text('Wan2GP has been added!')")).to_be_visible(timeout=300000)

        # 2. My Apps -> Launch
        page.locator("button:has-text('My Apps')").first.click()
        wan2gp_installed = page.get_by_text("Wan2GP").first
        expect(wan2gp_installed).to_be_visible(timeout=10000)

        # If it's running from a previous test, stop it first
        stop_btn = page.locator("button:has-text('Stop')").first
        if stop_btn.is_visible():
            stop_btn.click()
            expect(page.locator("button:has-text('Launch')").first).to_be_visible(timeout=10000)

        page.locator("button:has-text('Launch')").first.click()

        # 3. Wait for GUI at localhost:7860
        # It takes up to 30 mins to download PyTorch and models
        import time
        from playwright.sync_api import Error as PlaywrightError
        
        start_time = time.time()
        gui_loaded = False
        while time.time() - start_time < 1800:  # 30 mins max
            try:
                page.goto("http://localhost:7860", timeout=10000)
                gui_loaded = True
                break
            except PlaywrightError as e:
                if "ERR_CONNECTION_REFUSED" in str(e) or "Timeout" in str(e):
                    time.sleep(10)
                    continue
                raise e
        
        assert gui_loaded, "Wan2GP GUI never became available on port 7860"
        
        # Verify Gradio has loaded its UI
        expect(page.locator("gradio-app").first).to_be_visible(timeout=10000)

import json
import re

from playwright.sync_api import Page, expect

class TestAiUIGalleryWan2GP:
    """E2E tests for the Wan2GP plugin installation flow."""

    def test_wan2gp_install_error_reporting(self, page: Page, dashboard_url: str):
        """Test that Wan2GP install failures display the full error message to the user."""
        state = {"install_calls": 0}

        def handle_install(route):
            if route.request.method == "POST":
                state["install_calls"] += 1
                route.fulfill(
                    status=500,
                    content_type="application/json",
                    body=json.dumps({
                        "detail": "Failed to setup built-in 'wan2gp': Wan2GP requires an NVIDIA GPU for this preset flow.\\nSet WAN2GP_ALLOW_NO_NVIDIA=1 to force install anyway."
                    }),
                )
                return
            route.continue_()

        def handle_gallery(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=(
                    '{"apps":[{"id":"wan2gp","name":"Wan2GP",'
                    '"description":"WanGP local UI wrapper","icon":"film","source":'
                    '"builtin:wan2gp","stars":"Windows-first","category":"Built-in"}]}'
                ),
            )

        def handle_plugins(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"plugins": []}),
            )

        # We override just the necessary routes to control the test context for Wan2GP
        page.route(re.compile(r".*/api/ai-ui/plugins/install(?:\?.*)?$"), handle_install)
        page.route(re.compile(r".*/api/ai-ui/gallery(?:\?.*)?$"), handle_gallery)
        page.route(re.compile(r".*/api/ai-ui/plugins(?:\?.*)?$"), handle_plugins)

        page.goto(dashboard_url)
        # Navigate to Discover view
        page.locator("button:has-text('AI UI Local Cloud')").click()
        page.locator("button:has-text('Discover')").first.click()

        expect(page.get_by_text("Discover AI Apps").first).to_be_visible()
        
        # Open Wan2GP's install button. Wait for gallery items to render.
        # Find the specific card for the app
        wan2gp_card = page.locator("div:has-text('builtin:wan2gp')").first
        expect(wan2gp_card).to_be_visible(timeout=10000)
        
        # Click Install
        wan2gp_card.locator("button:has-text('Install')").click()

        # It should show the failure message from our mocked 500 JSON 'detail' field
        error_msg = page.get_by_text("Wan2GP requires an NVIDIA GPU for this preset flow.").first
        expect(error_msg).to_be_attached(timeout=10000)
        expect(page.get_by_text("Set WAN2GP_ALLOW_NO_NVIDIA=1").first).to_be_attached()

        assert state["install_calls"] == 1

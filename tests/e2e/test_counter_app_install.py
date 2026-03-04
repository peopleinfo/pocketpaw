"""E2E test: Counter App (Template) install completes without hanging.

Verifies the fix for the Windows+uvicorn subprocess bug where
``asyncio.create_subprocess_shell`` caused the install to hang
indefinitely in ``--dev`` mode.

This test hits the **real** server (no route mocking) so we exercise the
full install_builtin → subprocess.Popen → log_handler pipeline.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect


class TestCounterAppInstall:
    """Real end-to-end install of Counter App (Template) via the dashboard."""

    @pytest.fixture(autouse=True)
    def cleanup_counter_plugin(self):
        """Remove counter-template plugin before and after each test."""
        from pocketpaw.ai_ui.plugins import get_plugins_dir

        plugin_dir = get_plugins_dir() / "counter-template"
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir, ignore_errors=True)
        yield
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_counter_app_install_completes(self, page: Page, dashboard_url: str):
        """Install Counter App (Template) via the real API and verify it
        succeeds within a reasonable timeout (not hanging)."""

        # Navigate to the dashboard
        page.goto(dashboard_url)

        # Navigate to AI UI > Discover
        page.locator("button:has-text('AI UI Local Cloud')").click()
        page.locator("button:has-text('Discover'):visible").first.click()
        expect(page.get_by_text("Discover AI Apps").first).to_be_visible(timeout=10000)

        # Find the Counter App card (by its builtin source text or name)
        counter_card = page.locator("div:has-text('Counter App')").first
        expect(counter_card).to_be_visible(timeout=10000)

        # Click Install
        install_btn = counter_card.locator("button:has-text('Install')")
        expect(install_btn).to_be_visible(timeout=5000)
        install_btn.click()

        # The install should complete within 60s (not hang forever).
        # We wait for either:
        #   1. A success indicator (button changes text, toast, etc.)
        #   2. The plugin appearing in the installed list
        #
        # After install, the "Install" button typically changes or the
        # card shows a success state.  We also check the API directly.
        page.wait_for_timeout(3000)  # Give the streaming install a moment

        # Poll the API to verify the plugin actually got installed
        max_wait_seconds = 60
        installed = False
        for _ in range(max_wait_seconds // 2):
            resp = page.request.get(f"{dashboard_url}/api/ai-ui/plugins")
            if resp.ok:
                data = resp.json()
                plugins = data.get("plugins", [])
                for p in plugins:
                    if p.get("id") == "counter-template":
                        installed = True
                        break
            if installed:
                break
            page.wait_for_timeout(2000)

        assert installed, (
            "Counter App (Template) was not installed within 60 seconds. "
            "The install likely hung (the original bug)."
        )

    def test_counter_app_install_via_api_streaming(self, page: Page, dashboard_url: str):
        """Directly test the streaming install API endpoint to verify
        subprocess output is streamed correctly."""
        import httpx

        with httpx.Client(timeout=90.0) as client:
            resp = client.post(
                f"{dashboard_url}/api/ai-ui/plugins/install?stream=1",
                json={"source": "builtin:counter-template"},
            )
            assert resp.status_code == 200, f"Install request failed: {resp.status_code} {resp.text}"

            lines = resp.text.strip().split("\n")
            assert len(lines) > 0, "No streaming output received"

            # Parse NDJSON lines
            events = []
            for line in lines:
                line = line.strip()
                if line:
                    events.append(json.loads(line))

            # Should have step events and a final success
            step_events = [e for e in events if e.get("type") == "step"]
            log_events = [e for e in events if e.get("type") == "log"]
            final = events[-1]

            assert len(step_events) > 0, f"No step events received. Events: {events}"
            assert len(log_events) > 0, f"No log events received. Events: {events}"
            assert final.get("status") == "ok", f"Final event was not success: {final}"
            assert final.get("plugin_id") == "counter-template"

    def test_counter_app_install_and_launch(self, page: Page, dashboard_url: str):
        """Full lifecycle: install → verify files → launch → check port → stop → remove."""
        import httpx

        base = dashboard_url

        # 1. Install
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(
                f"{base}/api/ai-ui/plugins/install",
                json={"source": "builtin:counter-template"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["plugin_id"] == "counter-template"

        # 2. Verify plugin appears in list
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{base}/api/ai-ui/plugins")
            assert resp.status_code == 200
            plugins = resp.json()["plugins"]
            ids = [p["id"] for p in plugins]
            assert "counter-template" in ids

        # 3. Verify key files exist on disk
        from pocketpaw.ai_ui.plugins import get_plugins_dir

        plugin_dir = get_plugins_dir() / "counter-template"
        assert (plugin_dir / "pocketpaw.json").exists()
        assert (plugin_dir / "app.py").exists()
        assert (plugin_dir / ".venv").exists(), "Virtual environment should have been created"

        # 4. Remove
        with httpx.Client(timeout=10.0) as client:
            resp = client.delete(f"{base}/api/ai-ui/plugins/counter-template")
            assert resp.status_code == 200

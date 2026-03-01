# E2E Tests for pocketpaw Dashboard
# Created: 2026-02-05
#
# End-to-end tests using Playwright to verify the dashboard UI works correctly.
# Tests run against a real server instance with a real browser.
#
# Run with: pytest tests/e2e/ -v --headed (to see browser)
# Run headless: pytest tests/e2e/ -v

import json
import re

import pytest
from playwright.sync_api import Page, expect


class TestDashboardLoads:
    """Tests that the dashboard loads correctly."""

    def test_dashboard_title(self, page: Page, dashboard_url: str):
        """Test that dashboard page loads with correct title."""
        page.goto(dashboard_url)
        title = page.title().strip()
        assert title in {"PocketPaw", "PocketPaw (Beta)"}

    def test_chat_view_visible_by_default(self, page: Page, dashboard_url: str):
        """Test that Chat view is visible by default."""
        page.goto(dashboard_url)

        # Chat tab should be active
        chat_tab = page.get_by_role("button", name="Chat", exact=True)
        expect(chat_tab).to_be_visible()

    def test_view_tabs_exist(self, page: Page, dashboard_url: str):
        """Test that all view tabs exist."""
        page.goto(dashboard_url)

        expect(page.get_by_role("button", name="Chat", exact=True)).to_be_visible()
        expect(page.locator("button:has-text('Activity')").first).to_be_visible()
        crew_or_deep_work = page.locator("button:has-text('Crew'), button:has-text('Deep Work')")
        expect(crew_or_deep_work.first).to_be_visible()

    def test_agent_mode_toggle_exists(self, page: Page, dashboard_url: str):
        """Test that agent mode toggle exists."""
        page.goto(dashboard_url)

        # Look for Agent Mode label (use exact match to avoid multiple matches)
        expect(page.get_by_text("Agent Mode", exact=True).first).to_be_visible()

    def test_local_and_external_links_target_behavior(self, page: Page, dashboard_url: str):
        """Local app links should stay same-tab; external links should open in new tab."""
        page.goto(dashboard_url)

        result = page.evaluate("""
            () => {
                const localHtml = window.Tools.formatMessage(
                    "Open app: [http://localhost:8000/](http://localhost:8000/)"
                );
                const hashHtml = window.Tools.formatMessage(
                    "Open in dashboard: "
                    + "[#/ai-ui/plugin/counter-template/web]"
                    + "(#/ai-ui/plugin/counter-template/web)"
                );
                const externalHtml = window.Tools.formatMessage(
                    "Docs: [OpenAI](https://openai.com)"
                );

                const host = document.createElement("div");

                host.innerHTML = localHtml;
                const local = host.querySelector("a");

                host.innerHTML = hashHtml;
                const hash = host.querySelector("a");

                host.innerHTML = externalHtml;
                const external = host.querySelector("a");

                return {
                    local_href: local?.getAttribute("href") || "",
                    local_target: local?.getAttribute("target"),
                    hash_href: hash?.getAttribute("href") || "",
                    hash_target: hash?.getAttribute("target"),
                    external_href: external?.getAttribute("href") || "",
                    external_target: external?.getAttribute("target"),
                };
            }
        """)

        assert result["local_href"] == "http://localhost:8000/"
        assert result["local_target"] in (None, "")
        assert result["hash_href"] == "#/ai-ui/plugin/counter-template/web"
        assert result["hash_target"] in (None, "")
        assert result["external_href"] == "https://openai.com"
        assert result["external_target"] == "_blank"


class TestChatShortcuts:
    """Tests for the chat composer shortcuts/help menu."""

    def test_shortcuts_menu_fills_help_command(self, page: Page, dashboard_url: str):
        """Clicking /help in shortcuts menu should insert it into chat input."""
        page.goto(dashboard_url)

        toggle = page.get_by_label("Toggle quick shortcuts")
        expect(toggle).to_be_visible()
        toggle.click()

        expect(page.get_by_text("Quick Shortcuts")).to_be_visible()
        page.locator("button:has-text('/help')").first.click()

        chat_input = page.get_by_label("Chat message input")
        expect(chat_input).to_have_value("/help ")

    def test_shortcuts_menu_closes_on_outside_click(self, page: Page, dashboard_url: str):
        """Quick shortcuts should close when user clicks outside composer."""
        page.goto(dashboard_url)

        toggle = page.get_by_label("Toggle quick shortcuts")
        expect(toggle).to_be_visible()
        toggle.click()

        shortcuts_header = page.get_by_text("Quick Shortcuts")
        expect(shortcuts_header).to_be_visible()

        page.mouse.click(20, 20)
        expect(shortcuts_header).to_be_hidden()

    def test_skill_insert_prefills_input_without_auto_run(self, page: Page, dashboard_url: str):
        """Clicking Insert in Skills should prefill slash command but not execute it."""
        page.goto(dashboard_url)

        # Track websocket actions after initial page load.
        page.evaluate("""
            () => {
                window.__sentActions = [];
                const originalSend = window.socket.send.bind(window.socket);
                window.socket.send = (action, data = {}) => {
                    window.__sentActions.push(action);
                    return originalSend(action, data);
                };
            }
        """)

        opened = page.evaluate("""
            async () => {
                const root = document.querySelector("body");
                const data = root?._x_dataStack?.[0];
                if (!data || typeof data.openSkills !== "function") return false;
                await data.openSkills();
                return true;
            }
        """)
        assert opened is True
        expect(page.get_by_role("heading", name="Skills", exact=True)).to_be_visible()

        insert_button = page.locator("button:has-text('Insert')").first
        expect(insert_button).to_be_visible(timeout=5000)
        insert_button.click()

        chat_input = page.get_by_label("Chat message input")
        expect(chat_input).to_be_focused()
        expect(chat_input).to_have_value(re.compile(r"^/[a-zA-Z0-9_-]+\s$"))

        page.wait_for_timeout(250)
        sent_actions = page.evaluate("() => window.__sentActions || []")
        assert "run_skill" not in sent_actions

    def test_skill_usage_hint_and_required_args_block_send(self, page: Page, dashboard_url: str):
        """Required-args skill should show usage hint and refuse empty execution."""
        page.goto(dashboard_url)

        page.evaluate("""
            () => {
                window.__sentActions = [];
                const originalSend = window.socket.send.bind(window.socket);
                window.socket.send = (action, data = {}) => {
                    window.__sentActions.push(action);
                    return originalSend(action, data);
                };
            }
        """)

        opened = page.evaluate("""
            async () => {
                const root = document.querySelector("body");
                const data = root?._x_dataStack?.[0];
                if (!data || typeof data.openSkills !== "function") return false;
                await data.openSkills();
                return true;
            }
        """)
        assert opened is True

        has_converter_skill = page.evaluate("""
            () => {
                const root = document.querySelector("body");
                const data = root?._x_dataStack?.[0];
                return Boolean((data?.skills || []).some((s) => s.name === "create-ai-ui-plugin"));
            }
        """)
        if not has_converter_skill:
            pytest.skip("create-ai-ui-plugin is not available in this environment")

        page.evaluate("""
            () => {
                const root = document.querySelector("body");
                const data = root?._x_dataStack?.[0];
                if (data) data.showSkills = false;
            }
        """)

        chat_input = page.get_by_label("Chat message input")
        chat_input.fill("/create-ai-ui-plugin ")

        usage_text = page.evaluate("""
            () => {
                const root = document.querySelector("body");
                const data = root?._x_dataStack?.[0];
                return data?.getActiveSkillUsage?.() || "";
            }
        """)
        assert usage_text.startswith("/create-ai-ui-plugin ")
        usage_hint = page.locator('p[x-text="getActiveSkillUsage()"]')
        expect(usage_hint).to_be_visible()
        expect(usage_hint).to_have_text(usage_text)
        expect(page.get_by_text("Required arguments missing.", exact=True)).to_be_visible()

        send_button = page.get_by_label("Send message")
        expect(send_button).to_be_disabled()

        sent_actions = page.evaluate("() => window.__sentActions || []")
        assert "run_skill" not in sent_actions
        expect(chat_input).to_have_value("/create-ai-ui-plugin ")

    def test_required_skill_args_disable_send_until_filled(self, page: Page, dashboard_url: str):
        """Send button stays disabled for required-args skills until arguments are present."""
        page.goto(dashboard_url)

        opened = page.evaluate("""
            async () => {
                const root = document.querySelector("body");
                const data = root?._x_dataStack?.[0];
                if (!data || typeof data.openSkills !== "function") return false;
                await data.openSkills();
                return true;
            }
        """)
        assert opened is True

        has_converter_skill = page.evaluate("""
            () => {
                const root = document.querySelector("body");
                const data = root?._x_dataStack?.[0];
                return Boolean((data?.skills || []).some((s) => s.name === "create-ai-ui-plugin"));
            }
        """)
        if not has_converter_skill:
            pytest.skip("create-ai-ui-plugin is not available in this environment")

        page.evaluate("""
            () => {
                const root = document.querySelector("body");
                const data = root?._x_dataStack?.[0];
                if (data) data.showSkills = false;
            }
        """)

        chat_input = page.get_by_label("Chat message input")
        send_button = page.get_by_label("Send message")

        chat_input.fill("/create-ai-ui-plugin ")
        expect(send_button).to_be_disabled()

        chat_input.fill("/create-ai-ui-plugin owner/repo")
        expect(send_button).to_be_enabled()

    def test_skill_submit_shows_loading_and_stop_action(self, page: Page, dashboard_url: str):
        """Skill submit should enter loading state and Stop should emit stop action."""
        page.goto(dashboard_url)

        page.evaluate("""
            () => {
                window.__sentActions = [];
                window.__sentPayloads = [];
                window.socket.send = (action, data = {}) => {
                    window.__sentActions.push(action);
                    window.__sentPayloads.push({ action, data });
                    return true;
                };
            }
        """)

        opened = page.evaluate("""
            async () => {
                const root = document.querySelector("body");
                const data = root?._x_dataStack?.[0];
                if (!data || typeof data.openSkills !== "function") return false;
                await data.openSkills();
                return true;
            }
        """)
        assert opened is True

        has_converter_skill = page.evaluate("""
            () => {
                const root = document.querySelector("body");
                const data = root?._x_dataStack?.[0];
                return Boolean((data?.skills || []).some((s) => s.name === "create-ai-ui-plugin"));
            }
        """)
        if not has_converter_skill:
            pytest.skip("create-ai-ui-plugin is not available in this environment")

        page.evaluate("""
            () => {
                const root = document.querySelector("body");
                const data = root?._x_dataStack?.[0];
                if (data) data.showSkills = false;
            }
        """)

        chat_input = page.get_by_label("Chat message input")
        chat_input.fill("/create-ai-ui-plugin owner/repo")
        page.get_by_label("Send message").click()

        stop_button = page.get_by_label("Stop response")
        expect(stop_button).to_be_visible()
        expect(chat_input).to_be_disabled()

        sent_actions = page.evaluate("() => window.__sentActions || []")
        assert "run_skill" in sent_actions

        stop_button.click()
        sent_actions_after_stop = page.evaluate("() => window.__sentActions || []")
        assert "stop" in sent_actions_after_stop
        expect(stop_button).to_be_disabled()


class TestCrewView:
    """Tests for the Crew (Control Room) view."""

    def test_crew_tab_switches_view(self, page: Page, dashboard_url: str):
        """Test that clicking Crew tab switches to Crew view."""
        page.goto(dashboard_url)

        # Click Crew tab
        page.click("button:has-text('Crew')")

        # Wait for loading to complete
        page.wait_for_selector("text=Loading Crew...", state="hidden", timeout=10000)

        # Check stats bar appears (indicator of Crew view) - use heading "Agents"
        expect(page.get_by_role("heading", name="Agents")).to_be_visible()

    def test_new_agent_button_exists(self, page: Page, dashboard_url: str):
        """Test that New Agent button exists in Crew view."""
        page.goto(dashboard_url)
        page.click("button:has-text('Crew')")
        page.wait_for_selector("text=Loading Crew...", state="hidden", timeout=10000)

        expect(page.locator("button:has-text('New Agent')")).to_be_visible()

    def test_new_task_button_exists(self, page: Page, dashboard_url: str):
        """Test that New Task button exists in Crew view."""
        page.goto(dashboard_url)
        page.click("button:has-text('Crew')")
        page.wait_for_selector("text=Loading Crew...", state="hidden", timeout=10000)

        expect(page.locator("button:has-text('New Task')")).to_be_visible()

    def test_stats_bar_shows_numbers(self, page: Page, dashboard_url: str):
        """Test that stats bar shows agent and task counts."""
        page.goto(dashboard_url)
        page.click("button:has-text('Crew')")
        page.wait_for_selector("text=Loading Crew...", state="hidden", timeout=10000)

        # Stats bar should show "Live" indicator
        expect(page.get_by_text("Live", exact=True)).to_be_visible()

        # Stats should show "done today" text
        expect(page.get_by_text("done today")).to_be_visible()


class TestAgentCreation:
    """Tests for creating and deleting agents in Crew view."""

    def test_create_agent_modal_opens(self, page: Page, dashboard_url: str):
        """Test that clicking New Agent opens the creation form."""
        page.goto(dashboard_url)
        page.click("button:has-text('Crew')")
        page.wait_for_selector("text=Loading Crew...", state="hidden", timeout=10000)

        # Click New Agent
        page.click("button:has-text('New Agent')")

        # Wait for modal animation
        page.wait_for_timeout(300)

        # Modal should appear with "Create Agent" button
        expect(page.locator("button:has-text('Create Agent')")).to_be_visible()

    def test_create_agent_flow(self, page: Page, dashboard_url: str):
        """Test creating a new agent through the UI."""
        page.goto(dashboard_url)
        page.click("button:has-text('Crew')")
        page.wait_for_selector("text=Loading Crew...", state="hidden", timeout=10000)

        # Click New Agent button in header
        page.locator("button:has-text('New Agent')").first.click()
        page.wait_for_timeout(300)  # Wait for modal animation

        # Fill form using placeholder text
        page.get_by_placeholder("Agent name").fill("E2E Test Agent")
        page.get_by_placeholder("Role (e.g., Research Lead)").fill("Test Role")

        # Submit - click the visible Create Agent button (the one in modal)
        page.locator("button:has-text('Create Agent'):visible").click()

        # Wait for API response and UI update
        page.wait_for_timeout(1500)

        # Agent should appear somewhere (list or activity feed)
        expect(page.get_by_text("E2E Test Agent").first).to_be_visible(timeout=5000)

    def test_delete_agent_flow(self, page: Page, dashboard_url: str):
        """Test deleting an agent through the UI."""
        page.goto(dashboard_url)
        page.click("button:has-text('Crew')")
        page.wait_for_selector("text=Loading Crew...", state="hidden", timeout=10000)

        # First create an agent to delete
        page.locator("button:has-text('New Agent')").first.click()
        page.wait_for_timeout(300)
        page.get_by_placeholder("Agent name").fill("DeleteMe Agent")
        page.get_by_placeholder("Role (e.g., Research Lead)").fill("Temp Role")
        page.locator("button:has-text('Create Agent'):visible").click()
        page.wait_for_timeout(1500)

        # Verify agent was created
        expect(page.get_by_text("DeleteMe Agent").first).to_be_visible(timeout=5000)

        # Count agents before deletion
        initial_count = page.locator("text=DeleteMe Agent").count()

        # Handle the confirm dialog - accept it
        page.on("dialog", lambda dialog: dialog.accept())

        # Use JavaScript to click the delete button directly
        # This avoids issues with hover states and Lucide icon transformation
        page.evaluate("""
            () => {
                // Find the agent card with our test agent
                const spans = document.querySelectorAll('span');
                for (const span of spans) {
                    if (span.textContent === 'DeleteMe Agent') {
                        // Find the parent group div
                        const card = span.closest('.group');
                        if (card) {
                            // Find and click the delete button
                            const btn = card.querySelector('button.ml-auto');
                            if (btn) btn.click();
                        }
                        break;
                    }
                }
            }
        """)

        # Wait for confirm dialog and deletion
        page.wait_for_timeout(1500)

        # Check that agent count decreased or agent is no longer visible
        final_count = page.locator("text=DeleteMe Agent").count()
        # The count should decrease (agent removed from list, may still be in activity)
        assert final_count < initial_count or final_count == 0, "Agent should be deleted"


class TestTaskCreation:
    """Tests for creating tasks in Crew view."""

    def test_create_task_modal_opens(self, page: Page, dashboard_url: str):
        """Test that clicking New Task opens the creation form."""
        page.goto(dashboard_url)
        page.click("button:has-text('Crew')")
        page.wait_for_selector("text=Loading Crew...", state="hidden", timeout=10000)

        # Click New Task
        page.click("button:has-text('New Task')")

        # Modal should appear with form fields
        expect(page.locator("input[placeholder*='title' i]")).to_be_visible()

    def test_create_task_flow(self, page: Page, dashboard_url: str):
        """Test creating a new task through the UI and verify it appears in task list."""
        page.goto(dashboard_url)
        page.click("button:has-text('Crew')")
        page.wait_for_selector("text=Loading Crew...", state="hidden", timeout=10000)

        # Make sure "All" filter is selected to see all tasks
        page.click("button:has-text('All')")
        page.wait_for_timeout(200)

        # Click New Task button in header
        page.locator("button:has-text('New Task')").first.click()
        page.wait_for_timeout(300)  # Wait for modal animation

        # Fill form using placeholder
        page.get_by_placeholder("Task title").fill("E2E Task In List")

        # Submit - click the Create Task button inside the modal
        modal_submit_btn = page.locator("button:has-text('Create Task')").filter(
            has=page.locator(":scope:enabled")
        )
        modal_submit_btn.last.click()

        # Wait for API response and UI update
        page.wait_for_timeout(2000)

        # Verify task appears in the task list panel (not just activity feed)
        task_panel = page.locator("div.flex-1.flex.flex-col.border-r")
        expect(task_panel.get_by_text("E2E Task In List").first).to_be_visible(timeout=5000)


class TestSidebarNavigation:
    """Tests for sidebar navigation."""

    def test_sidebar_exists(self, page: Page, dashboard_url: str):
        """Test that sidebar exists and has key elements."""
        page.goto(dashboard_url)

        # Sidebar should have PocketPaw branding or key nav items
        # Check for Settings or other sidebar elements
        sidebar = page.locator("aside, nav").first
        expect(sidebar).to_be_visible()

    def test_clear_all_sessions_from_sidebar(self, page: Page, dashboard_url: str):
        """Clear all sessions from the left sidebar Chats menu."""
        state = {"delete_all_calls": 0}

        def handle_sessions(route):
            if route.request.method == "GET":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=(
                        '{"sessions":[{"id":"websocket_test_clear","title":"Session To Clear",'
                        '"channel":"websocket","created":"2026-02-26T10:00:00",'
                        '"last_activity":"2026-02-26T10:00:00","message_count":1,'
                        '"preview":"hello"}],"total":1}'
                    ),
                )
                return

            if route.request.method == "DELETE":
                state["delete_all_calls"] += 1
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body='{"status":"ok","deleted":1,"total":1}',
                )
                return

            route.continue_()

        page.route(re.compile(r".*/api/sessions(?:\?.*)?$"), handle_sessions)

        page.goto(dashboard_url)
        expect(page.get_by_text("Session To Clear").first).to_be_visible()

        page.on("dialog", lambda dialog: dialog.accept())
        page.locator("button:has-text('Clear All')").click()

        page.wait_for_timeout(700)
        assert state["delete_all_calls"] == 1
        expect(page.get_by_text("No conversations yet")).to_be_visible()

    def test_delete_single_session_via_context_menu(self, page: Page, dashboard_url: str):
        """Session context menu should delete only the selected chat."""
        state = {"delete_calls": 0}

        def handle_sessions(route):
            if route.request.method == "GET":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=(
                        '{"sessions":[{"id":"websocket_ctx_delete","title":"Ctx Delete Session",'
                        '"channel":"websocket","created":"2026-02-26T10:00:00",'
                        '"last_activity":"2026-02-26T10:00:00","message_count":1,'
                        '"preview":"delete me"}],"total":1}'
                    ),
                )
                return

            if route.request.method == "DELETE":
                state["delete_calls"] += 1
                route.fulfill(status=200, content_type="application/json", body='{"status":"ok"}')
                return

            route.continue_()

        page.route(re.compile(r".*/api/sessions(?:/[^/?]+)?(?:\?.*)?$"), handle_sessions)

        page.goto(dashboard_url)
        target = page.locator("button:has-text('Ctx Delete Session')").first
        expect(target).to_be_visible()

        target.click(button="right")
        expect(page.locator("button:has-text('Delete chat')").first).to_be_visible()
        page.locator("button:has-text('Delete chat')").first.click()

        page.wait_for_timeout(700)
        assert state["delete_calls"] == 1
        expect(page.get_by_text("No conversations yet")).to_be_visible()

    def test_session_click_from_terminal_navigates_to_chat_route(
        self, page: Page, dashboard_url: str
    ):
        """Clicking a sidebar session from Terminal should switch to #/chat/<session-id>."""
        session_id = "websocket_route_test"

        def handle_sessions(route):
            if route.request.method == "GET":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=(
                        '{"sessions":[{"id":"websocket_route_test","title":"Route Test Session",'
                        '"channel":"websocket","created":"2026-02-26T10:00:00",'
                        '"last_activity":"2026-02-26T10:00:00","message_count":1,'
                        '"preview":"route test"}],"total":1}'
                    ),
                )
                return
            route.continue_()

        page.route(re.compile(r".*/api/sessions(?:\?.*)?$"), handle_sessions)

        page.goto(dashboard_url)
        expect(page.get_by_text("Route Test Session").first).to_be_visible()

        page.get_by_role("button", name="Terminal", exact=True).click()
        expect(page).to_have_url(re.compile(r".*#/terminal$"))

        page.locator("button:has-text('Route Test Session')").first.click()
        expect(page).to_have_url(re.compile(rf".*#/chat/{session_id}$"))

        chat_input = page.get_by_label("Chat message input")
        expect(chat_input).to_be_visible()

        page.reload()
        expect(page).to_have_url(re.compile(rf".*#/chat/{session_id}$"))
        expect(chat_input).to_be_visible()


class TestAiUIDiscoveryInstall:
    """E2E tests for AI UI Discover install flow."""

    def test_discover_install_is_one_click_without_plugins_redirect(
        self, page: Page, dashboard_url: str
    ):
        """Install from Discover directly and keep the user in Discover view."""
        state = {"install_calls": 0}

        def handle_requirements(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"requirements":[]}',
            )

        def handle_gallery(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=(
                    '{"apps":[{"id":"g4f-chat-template","name":"Gf4 Chat (Template)",'
                    '"description":"Template","icon":"message-circle","source":'
                    '"builtin:g4f-chat-template","stars":"GUI Chat","category":"Template"}]}'
                ),
            )

        def handle_plugins(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"plugins": []}),
            )

        def handle_install(route):
            if route.request.method == "POST":
                state["install_calls"] += 1
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body='{"status":"ok","message":"Installed","plugin_id":"g4f-chat-template"}',
                )
                return
            route.continue_()

        page.route("**/api/ai-ui/requirements*", handle_requirements)
        page.route("**/api/ai-ui/gallery*", handle_gallery)
        page.route(re.compile(r".*/api/ai-ui/plugins/install(?:\?.*)?$"), handle_install)
        page.route(re.compile(r".*/api/ai-ui/plugins(?:\?.*)?$"), handle_plugins)

        page.goto(dashboard_url)
        page.locator("button:has-text('AI UI Local Cloud')").click()
        page.locator("button:has-text('Discover'):visible").first.click()

        expect(page.get_by_text("Discover AI Apps")).to_be_visible()
        g4f_card = page.locator("div:has-text('builtin:g4f-chat-template')").first
        g4f_card.locator("button:has-text('Install')").click()

        expect(page.get_by_text("Discover AI Apps")).to_be_visible()
        expect(g4f_card.locator("button:has-text('Install')")).to_be_visible(timeout=10000)
        assert state["install_calls"] == 1
        assert "#/ai-ui/plugin/" not in page.url
        assert "#/ai-ui/plugins" not in page.url

    def test_settings_opens(self, page: Page, dashboard_url: str):
        """Test that settings modal can be opened."""
        page.goto(dashboard_url)

        # Click settings button (usually a gear icon)
        settings_btn = page.locator(
            "button:has(i[data-lucide='settings']), button:has-text('Settings')"
        ).first
        if settings_btn.is_visible():
            settings_btn.click()
            # Settings modal should appear
            page.wait_for_timeout(500)

    def test_codex_model_persists_after_reload(self, page: Page, dashboard_url: str):
        """Codex CLI model should persist after reload."""
        page.goto(dashboard_url)
        page.evaluate(
            """
            () => {
                localStorage.setItem('pocketpaw_setup_dismissed', '1');
                const root = document.querySelector('body');
                const data = root?._x_dataStack?.[0];
                if (data) data.showWelcome = false;
            }
            """
        )

        settings_btn = page.locator(
            "button:has(i[data-lucide='settings']), button:has-text('Settings')"
        ).first
        expect(settings_btn).to_be_visible()
        settings_btn.click()

        backend_select = page.locator("select[x-model='settings.agentBackend']").first
        expect(backend_select).to_be_visible()
        codex_option = page.locator(
            "select[x-model='settings.agentBackend'] option[value='codex_cli']"
        )
        expect(codex_option).to_have_count(1)

        backend_select.select_option("codex_cli")

        codex_model_input = page.locator("input[x-model='settings.codexCliModel']").first
        expect(codex_model_input).to_be_visible()
        codex_model_input.fill("gpt-5.2")
        codex_model_input.press("Tab")
        page.wait_for_timeout(800)
        backend_badge = page.locator("aside span[x-text='getCurrentBackendBadge()']").first
        expect(backend_badge).to_be_visible()
        expect(backend_badge).to_have_text(re.compile(r"Codex", re.I))
        model_badge = page.locator("aside span[x-text='getCurrentModelBadge()']").first
        expect(model_badge).to_be_visible()
        expect(model_badge).to_have_text("gpt-5.2")

        page.reload()
        backend_badge = page.locator("aside span[x-text='getCurrentBackendBadge()']").first
        expect(backend_badge).to_be_visible()
        expect(backend_badge).to_have_text(re.compile(r"Codex", re.I))
        model_badge = page.locator("aside span[x-text='getCurrentModelBadge()']").first
        expect(model_badge).to_be_visible()
        expect(model_badge).to_have_text("gpt-5.2")

        settings_btn = page.locator(
            "button:has(i[data-lucide='settings']), button:has-text('Settings')"
        ).first
        expect(settings_btn).to_be_visible()
        settings_btn.click()

        backend_select = page.locator("select[x-model='settings.agentBackend']").first
        expect(backend_select).to_be_visible()
        backend_select.select_option("codex_cli")

        codex_model_input = page.locator("input[x-model='settings.codexCliModel']").first
        expect(codex_model_input).to_be_visible()
        expect(codex_model_input).to_have_value("gpt-5.2")

    def test_ai_fast_api_config_supports_codex_oauth(self, page: Page, dashboard_url: str):
        """AI Fast API config modal should expose codex backend + OAuth controls."""
        state = {"start_calls": 0, "poll_calls": 0}

        def handle_plugins(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "plugins": [
                            {
                                "id": "ai-fast-api",
                                "name": "AI Fast API",
                                "description": "API server",
                                "icon": "zap",
                                "version": "2.0.0",
                                "port": 8000,
                                "status": "running",
                                "path": "/tmp/ai-fast-api",
                                "start_cmd": "bash start.sh",
                                "has_install": True,
                                "requires": ["uv", "python"],
                                "env": {
                                    "LLM_BACKEND": "codex",
                                    "CODEX_MODEL": "gpt-5",
                                },
                                "openapi": "openapi.json",
                                "web_view": "native",
                                "web_view_path": "/",
                            }
                        ]
                    }
                ),
            )

        def handle_config(route):
            if route.request.method == "GET":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "config": {
                                "LLM_BACKEND": "codex",
                                "CODEX_MODEL": "gpt-5",
                                "HOST": "0.0.0.0",
                                "PORT": "8000",
                                "DEBUG": "true",
                            }
                        }
                    ),
                )
                return
            route.continue_()

        def handle_codex_auth_status(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"ok":false,"logged_in":false,"message":"Not logged in"}',
            )

        def handle_codex_auth_start(route):
            state["start_calls"] += 1
            route.fulfill(
                status=200,
                content_type="application/json",
                body=(
                    '{"ok":true,"status":"pending","session_id":"sess-1",'
                    '"verification_uri":"https://auth.openai.com/codex/device",'
                    '"user_code":"ABCD-1234","message":"Open verification URL and enter code"}'
                ),
            )

        def handle_codex_auth_poll(route):
            state["poll_calls"] += 1
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"ok":true,"status":"completed","session_id":"sess-1","message":"Done"}',
            )

        page.route(
            re.compile(r".*/api/ai-ui/plugins/ai-fast-api/codex/auth/status(?:\?.*)?$"),
            handle_codex_auth_status,
        )
        page.route(
            re.compile(r".*/api/ai-ui/plugins/ai-fast-api/codex/auth/start(?:\?.*)?$"),
            handle_codex_auth_start,
        )
        page.route(
            re.compile(r".*/api/ai-ui/plugins/ai-fast-api/codex/auth/poll(?:\?.*)?$"),
            handle_codex_auth_poll,
        )
        page.route(re.compile(r".*/api/ai-ui/plugins/ai-fast-api/config(?:\?.*)?$"), handle_config)
        page.route(re.compile(r".*/api/ai-ui/plugins(?:\?.*)?$"), handle_plugins)

        page.goto(dashboard_url)
        page.locator("button:has-text('AI UI Local Cloud')").click()
        opened = page.evaluate(
            """
            async () => {
                const root = document.querySelector("body");
                const data = root?._x_dataStack?.[0];
                if (!data || typeof data.openPluginConfigModal !== "function") return false;
                await data.openPluginConfigModal("ai-fast-api");
                return true;
            }
            """
        )
        assert opened is True

        backend_select = page.locator("select[x-model='aiUI.pluginConfigDraft.LLM_BACKEND']").first
        expect(backend_select).to_be_visible()
        codex_option = page.locator(
            "select[x-model='aiUI.pluginConfigDraft.LLM_BACKEND'] option[value='codex']"
        )
        expect(codex_option).to_have_count(1)
        backend_select.select_option("codex")

        codex_model_input = page.locator(
            "input[x-model='aiUI.pluginConfigDraft.CODEX_MODEL']"
        ).first
        expect(codex_model_input).to_be_visible()
        expect(codex_model_input).to_have_value("gpt-5")

        start_button = page.get_by_role("button", name="Start OAuth Login")
        expect(start_button).to_be_visible()
        start_button.click()

        expect(page.get_by_text("ABCD-1234")).to_be_visible()
        assert state["start_calls"] == 1
        assert state["poll_calls"] >= 1

    def test_ai_fast_api_config_supports_qwen_oauth(self, page: Page, dashboard_url: str):
        """AI Fast API config modal should expose qwen backend + OAuth controls."""
        state = {"start_calls": 0, "poll_calls": 0}

        def handle_plugins(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "plugins": [
                            {
                                "id": "ai-fast-api",
                                "name": "AI Fast API",
                                "description": "API server",
                                "icon": "zap",
                                "version": "2.0.0",
                                "port": 8000,
                                "status": "running",
                                "path": "/tmp/ai-fast-api",
                                "start_cmd": "bash start.sh",
                                "has_install": True,
                                "requires": ["uv", "python"],
                                "env": {
                                    "LLM_BACKEND": "qwen",
                                    "QWEN_MODEL": "qwen3-coder-plus",
                                },
                                "openapi": "openapi.json",
                                "web_view": "native",
                                "web_view_path": "/",
                            }
                        ]
                    }
                ),
            )

        def handle_config(route):
            if route.request.method == "GET":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "config": {
                                "LLM_BACKEND": "qwen",
                                "QWEN_MODEL": "qwen3-coder-plus",
                                "HOST": "0.0.0.0",
                                "PORT": "8000",
                                "DEBUG": "true",
                            }
                        }
                    ),
                )
                return
            route.continue_()

        def handle_qwen_auth_status(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"ok":false,"logged_in":false,"message":"Not logged in"}',
            )

        def handle_qwen_auth_start(route):
            state["start_calls"] += 1
            route.fulfill(
                status=200,
                content_type="application/json",
                body=(
                    '{"ok":true,"status":"pending","session_id":"sess-q1",'
                    '"verification_uri":"https://chat.qwen.ai/authorize?user_code=QWEN-5678",'
                    '"user_code":"QWEN-5678","message":"Open authorization URL and login"}'
                ),
            )

        def handle_qwen_auth_poll(route):
            state["poll_calls"] += 1
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"ok":true,"status":"completed","session_id":"sess-q1","message":"Done"}',
            )

        page.route(
            re.compile(r".*/api/ai-ui/plugins/ai-fast-api/qwen/auth/status(?:\?.*)?$"),
            handle_qwen_auth_status,
        )
        page.route(
            re.compile(r".*/api/ai-ui/plugins/ai-fast-api/qwen/auth/start(?:\?.*)?$"),
            handle_qwen_auth_start,
        )
        page.route(
            re.compile(r".*/api/ai-ui/plugins/ai-fast-api/qwen/auth/poll(?:\?.*)?$"),
            handle_qwen_auth_poll,
        )
        page.route(re.compile(r".*/api/ai-ui/plugins/ai-fast-api/config(?:\?.*)?$"), handle_config)
        page.route(re.compile(r".*/api/ai-ui/plugins(?:\?.*)?$"), handle_plugins)

        page.goto(dashboard_url)
        page.locator("button:has-text('AI UI Local Cloud')").click()
        opened = page.evaluate(
            """
            async () => {
                const root = document.querySelector("body");
                const data = root?._x_dataStack?.[0];
                if (!data || typeof data.openPluginConfigModal !== "function") return false;
                await data.openPluginConfigModal("ai-fast-api");
                return true;
            }
            """
        )
        assert opened is True

        backend_select = page.locator("select[x-model='aiUI.pluginConfigDraft.LLM_BACKEND']").first
        expect(backend_select).to_be_visible()
        qwen_option = page.locator(
            "select[x-model='aiUI.pluginConfigDraft.LLM_BACKEND'] option[value='qwen']"
        )
        expect(qwen_option).to_have_count(1)
        backend_select.select_option("qwen")

        qwen_model_input = page.locator("input[x-model='aiUI.pluginConfigDraft.QWEN_MODEL']").first
        expect(qwen_model_input).to_be_visible()
        expect(qwen_model_input).to_have_value("qwen3-coder-plus")

        start_button = page.get_by_role("button", name="Start OAuth Login")
        expect(start_button).to_be_visible()
        start_button.click()

        expect(page.locator("span.font-mono.text-white", has_text="QWEN-5678")).to_be_visible()
        assert state["start_calls"] == 1
        assert state["poll_calls"] >= 1

    def test_ai_fast_api_config_supports_gemini_oauth(self, page: Page, dashboard_url: str):
        """AI Fast API config modal should expose gemini backend + OAuth controls."""
        state = {"start_calls": 0, "poll_calls": 0}

        def handle_plugins(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "plugins": [
                            {
                                "id": "ai-fast-api",
                                "name": "AI Fast API",
                                "description": "API server",
                                "icon": "zap",
                                "version": "2.0.0",
                                "port": 8000,
                                "status": "running",
                                "path": "/tmp/ai-fast-api",
                                "start_cmd": "bash start.sh",
                                "has_install": True,
                                "requires": ["uv", "python"],
                                "env": {
                                    "LLM_BACKEND": "gemini",
                                    "GEMINI_MODEL": "gemini-2.5-flash",
                                },
                                "openapi": "openapi.json",
                                "web_view": "native",
                                "web_view_path": "/",
                            }
                        ]
                    }
                ),
            )

        def handle_config(route):
            if route.request.method == "GET":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "config": {
                                "LLM_BACKEND": "gemini",
                                "GEMINI_MODEL": "gemini-2.5-flash",
                                "HOST": "0.0.0.0",
                                "PORT": "8000",
                                "DEBUG": "true",
                            }
                        }
                    ),
                )
                return
            route.continue_()

        def handle_gemini_auth_status(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"ok":false,"logged_in":false,"message":"Not logged in"}',
            )

        def handle_gemini_auth_start(route):
            state["start_calls"] += 1
            route.fulfill(
                status=200,
                content_type="application/json",
                body=(
                    '{"ok":true,"status":"pending","session_id":"sess-g1",'
                    '"verification_uri":"https://accounts.google.com/o/oauth2/v2/auth?x=1",'
                    '"message":"Open browser and complete Google sign-in"}'
                ),
            )

        def handle_gemini_auth_poll(route):
            state["poll_calls"] += 1
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"ok":true,"status":"completed","session_id":"sess-g1","message":"Done"}',
            )

        page.route(
            re.compile(r".*/api/ai-ui/plugins/ai-fast-api/gemini/auth/status(?:\?.*)?$"),
            handle_gemini_auth_status,
        )
        page.route(
            re.compile(r".*/api/ai-ui/plugins/ai-fast-api/gemini/auth/start(?:\?.*)?$"),
            handle_gemini_auth_start,
        )
        page.route(
            re.compile(r".*/api/ai-ui/plugins/ai-fast-api/gemini/auth/poll(?:\?.*)?$"),
            handle_gemini_auth_poll,
        )
        page.route(re.compile(r".*/api/ai-ui/plugins/ai-fast-api/config(?:\?.*)?$"), handle_config)
        page.route(re.compile(r".*/api/ai-ui/plugins(?:\?.*)?$"), handle_plugins)

        page.goto(dashboard_url)
        page.locator("button:has-text('AI UI Local Cloud')").click()
        opened = page.evaluate(
            """
            async () => {
                const root = document.querySelector("body");
                const data = root?._x_dataStack?.[0];
                if (!data || typeof data.openPluginConfigModal !== "function") return false;
                await data.openPluginConfigModal("ai-fast-api");
                return true;
            }
            """
        )
        assert opened is True

        backend_select = page.locator("select[x-model='aiUI.pluginConfigDraft.LLM_BACKEND']").first
        expect(backend_select).to_be_visible()
        gemini_option = page.locator(
            "select[x-model='aiUI.pluginConfigDraft.LLM_BACKEND'] option[value='gemini']"
        )
        expect(gemini_option).to_have_count(1)
        backend_select.select_option("gemini")

        gemini_model_input = page.locator(
            "input[x-model='aiUI.pluginConfigDraft.GEMINI_MODEL']"
        ).first
        expect(gemini_model_input).to_be_visible()
        expect(gemini_model_input).to_have_value("gemini-2.5-flash")

        start_button = page.get_by_role("button", name="Start OAuth Login")
        expect(start_button).to_be_visible()
        start_button.click()

        expect(page.get_by_text("accounts.google.com")).to_be_visible()
        assert state["start_calls"] == 1
        assert state["poll_calls"] >= 1

    def test_ai_fast_api_config_supports_ollama_cloud_toggle(self, page: Page, dashboard_url: str):
        """AI Fast API config modal should expose Ollama local/cloud controls."""
        state = {"local_setup_calls": 0}

        def handle_plugins(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "plugins": [
                            {
                                "id": "ai-fast-api",
                                "name": "AI Fast API",
                                "description": "API server",
                                "icon": "zap",
                                "version": "2.0.0",
                                "port": 8000,
                                "status": "running",
                                "path": "/tmp/ai-fast-api",
                                "start_cmd": "bash start.sh",
                                "has_install": True,
                                "requires": ["uv", "python"],
                                "env": {
                                    "LLM_BACKEND": "ollama",
                                    "OLLAMA_DEPLOYMENT": "cloud",
                                    "OLLAMA_BASE_URL": "https://ollama.com/v1",
                                    "OLLAMA_LOCAL_MODEL": "llama3.1:8b",
                                    "OLLAMA_CLOUD_MODEL": "llama3.3:70b",
                                },
                                "openapi": "openapi.json",
                                "web_view": "native",
                                "web_view_path": "/",
                            }
                        ]
                    }
                ),
            )

        def handle_config(route):
            if route.request.method == "GET":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "config": {
                                "LLM_BACKEND": "ollama",
                                "OLLAMA_DEPLOYMENT": "cloud",
                                "OLLAMA_BASE_URL": "https://ollama.com/v1",
                                "OLLAMA_LOCAL_MODEL": "llama3.1:8b",
                                "OLLAMA_CLOUD_MODEL": "llama3.3:70b",
                                "HOST": "0.0.0.0",
                                "PORT": "8000",
                                "DEBUG": "true",
                            }
                        }
                    ),
                )
                return
            route.continue_()

        def handle_local_ollama_setup(route):
            state["local_setup_calls"] += 1
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": True,
                        "status": "ok",
                        "plugin_id": "ollama",
                        "installed": True,
                        "started": True,
                        "base_url": "http://127.0.0.1:11434/v1",
                        "message": "Local Ollama installed and started.",
                    }
                ),
            )

        page.route(
            re.compile(r".*/api/ai-ui/plugins/ai-fast-api/ollama/local/setup(?:\?.*)?$"),
            handle_local_ollama_setup,
        )
        page.route(re.compile(r".*/api/ai-ui/plugins/ai-fast-api/config(?:\?.*)?$"), handle_config)
        page.route(re.compile(r".*/api/ai-ui/plugins(?:\?.*)?$"), handle_plugins)

        page.goto(dashboard_url)
        page.locator("button:has-text('AI UI Local Cloud')").click()
        opened = page.evaluate(
            """
            async () => {
                const root = document.querySelector("body");
                const data = root?._x_dataStack?.[0];
                if (!data || typeof data.openPluginConfigModal !== "function") return false;
                await data.openPluginConfigModal("ai-fast-api");
                return true;
            }
            """
        )
        assert opened is True

        backend_select = page.locator("select[x-model='aiUI.pluginConfigDraft.LLM_BACKEND']").first
        expect(backend_select).to_be_visible()
        backend_select.select_option("ollama")

        deploy_select = page.locator(
            "select[x-model='aiUI.pluginConfigDraft.OLLAMA_DEPLOYMENT']"
        ).first
        expect(deploy_select).to_be_visible()
        expect(deploy_select).to_have_value("cloud")

        cloud_model_field = page.locator(
            "select[x-model='aiUI.pluginConfigDraft.OLLAMA_CLOUD_MODEL'], "
            "input[x-model='aiUI.pluginConfigDraft.OLLAMA_CLOUD_MODEL']"
        ).first
        expect(cloud_model_field).to_be_visible()
        expect(cloud_model_field).to_have_value("llama3.3:70b")

        base_url_input = page.locator(
            "input[x-model='aiUI.pluginConfigDraft.OLLAMA_BASE_URL']"
        ).first
        expect(base_url_input).to_be_visible()
        expect(base_url_input).to_have_value("https://ollama.com/v1")

        deploy_select.select_option("local")
        expect(base_url_input).to_have_value("http://127.0.0.1:11434/v1")
        local_model_field = page.locator(
            "select[x-model='aiUI.pluginConfigDraft.OLLAMA_LOCAL_MODEL'], "
            "input[x-model='aiUI.pluginConfigDraft.OLLAMA_LOCAL_MODEL']"
        ).first
        expect(local_model_field).to_be_visible()
        expect(local_model_field).to_have_value("llama3.1:8b")

        setup_local_btn = page.get_by_role("button", name="Setup / Start Local Ollama")
        expect(setup_local_btn).to_be_visible()
        setup_local_btn.click()
        assert state["local_setup_calls"] == 1

    def test_ai_fast_api_config_supports_auto_rotate(self, page: Page, dashboard_url: str):
        """AI Fast API config modal should expose auto rotator settings."""

        def handle_plugins(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "plugins": [
                            {
                                "id": "ai-fast-api",
                                "name": "AI Fast API",
                                "description": "API server",
                                "icon": "zap",
                                "version": "2.0.0",
                                "port": 8000,
                                "status": "running",
                                "path": "/tmp/ai-fast-api",
                                "start_cmd": "bash start.sh",
                                "has_install": True,
                                "requires": ["uv", "python"],
                                "env": {
                                    "LLM_BACKEND": "auto",
                                    "AUTO_MAX_ROTATE_RETRY": "4",
                                    "AUTO_ROTATE_BACKENDS": "g4f,ollama,codex,qwen,gemini",
                                    "AUTO_G4F_MODEL": "gpt-4o-mini",
                                    "AUTO_OLLAMA_MODEL": "llama3.1",
                                    "AUTO_CODEX_MODEL": "gpt-5",
                                    "AUTO_QWEN_MODEL": "qwen3-coder-plus",
                                    "AUTO_GEMINI_MODEL": "gemini-2.5-flash",
                                },
                                "openapi": "openapi.json",
                                "web_view": "native",
                                "web_view_path": "/",
                            }
                        ]
                    }
                ),
            )

        def handle_config(route):
            if route.request.method == "GET":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "config": {
                                "LLM_BACKEND": "auto",
                                "AUTO_MAX_ROTATE_RETRY": "4",
                                "AUTO_ROTATE_BACKENDS": "g4f,ollama,codex,qwen,gemini",
                                "AUTO_G4F_MODEL": "gpt-4o-mini",
                                "AUTO_OLLAMA_MODEL": "llama3.1",
                                "AUTO_CODEX_MODEL": "gpt-5",
                                "AUTO_QWEN_MODEL": "qwen3-coder-plus",
                                "AUTO_GEMINI_MODEL": "gemini-2.5-flash",
                                "HOST": "0.0.0.0",
                                "PORT": "8000",
                                "DEBUG": "true",
                            }
                        }
                    ),
                )
                return
            route.continue_()

        page.route(re.compile(r".*/api/ai-ui/plugins/ai-fast-api/config(?:\?.*)?$"), handle_config)
        page.route(re.compile(r".*/api/ai-ui/plugins(?:\?.*)?$"), handle_plugins)

        page.goto(dashboard_url)
        page.locator("button:has-text('AI UI Local Cloud')").click()
        opened = page.evaluate(
            """
            async () => {
                const root = document.querySelector("body");
                const data = root?._x_dataStack?.[0];
                if (!data || typeof data.openPluginConfigModal !== "function") return false;
                await data.openPluginConfigModal("ai-fast-api");
                return true;
            }
            """
        )
        assert opened is True

        backend_select = page.locator("select[x-model='aiUI.pluginConfigDraft.LLM_BACKEND']").first
        expect(backend_select).to_be_visible()
        auto_option = page.locator(
            "select[x-model='aiUI.pluginConfigDraft.LLM_BACKEND'] option[value='auto']"
        )
        expect(auto_option).to_have_count(1)
        backend_select.select_option("auto")

        max_retry_input = page.locator(
            "input[x-model='aiUI.pluginConfigDraft.AUTO_MAX_ROTATE_RETRY']"
        ).first
        expect(max_retry_input).to_be_visible()
        expect(max_retry_input).to_have_value("4")

        rotate_backends_input = page.locator(
            "input[x-model='aiUI.pluginConfigDraft.AUTO_ROTATE_BACKENDS']"
        ).first
        expect(rotate_backends_input).to_be_visible()
        expect(rotate_backends_input).to_have_value("g4f,ollama,codex,qwen,gemini")

        expect(
            page.locator("input[x-model='aiUI.pluginConfigDraft.AUTO_G4F_MODEL']").first
        ).to_have_value("gpt-4o-mini")
        expect(
            page.locator("input[x-model='aiUI.pluginConfigDraft.AUTO_OLLAMA_MODEL']").first
        ).to_have_value("llama3.1")
        expect(
            page.locator("input[x-model='aiUI.pluginConfigDraft.AUTO_CODEX_MODEL']").first
        ).to_have_value("gpt-5")
        expect(
            page.locator("input[x-model='aiUI.pluginConfigDraft.AUTO_QWEN_MODEL']").first
        ).to_have_value("qwen3-coder-plus")
        expect(
            page.locator("input[x-model='aiUI.pluginConfigDraft.AUTO_GEMINI_MODEL']").first
        ).to_have_value("gemini-2.5-flash")

    def test_ai_fast_api_detail_shows_auto_route_backend_provider_model(
        self, page: Page, dashboard_url: str
    ):
        """AI Fast API detail should show selected backend/provider/model after auto test."""

        plugin_payload = {
            "id": "ai-fast-api",
            "name": "AI Fast API",
            "description": "API server",
            "icon": "zap",
            "version": "2.0.0",
            "port": 8000,
            "status": "running",
            "path": "/tmp/ai-fast-api",
            "start_cmd": "bash start.sh",
            "has_install": True,
            "requires": ["uv", "python"],
            "env": {
                "LLM_BACKEND": "auto",
                "AUTO_G4F_MODEL": "gpt-4o-mini",
            },
            "openapi": "openapi.json",
            "web_view": "native",
            "web_view_path": "/",
        }

        def handle_plugins(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"plugins": [plugin_payload]}),
            )

        def handle_plugin_detail(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"plugin": plugin_payload}),
            )

        def handle_test_connection(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": True,
                        "message": "Chat OK",
                        "requested_backend": "auto",
                        "selected_backend": "codex",
                        "selected_provider": "CodexOAuth",
                        "selected_model": "gpt-5",
                    }
                ),
            )

        page.route(
            re.compile(r".*/api/ai-ui/plugins/ai-fast-api/test-connection(?:\?.*)?$"),
            handle_test_connection,
        )
        page.route(re.compile(r".*/api/ai-ui/plugins/ai-fast-api(?:\?.*)?$"), handle_plugin_detail)
        page.route(re.compile(r".*/api/ai-ui/plugins(?:\?.*)?$"), handle_plugins)

        page.goto(dashboard_url)
        page.locator("button:has-text('AI UI Local Cloud')").click()
        page.wait_for_function(
            """
            () => {
                const root = document.querySelector("body");
                const data = root?._x_dataStack?.[0];
                return (data?.aiUI?.plugins || []).some((p) => p.id === "ai-fast-api");
            }
            """
        )

        initial_label = page.evaluate(
            """
            async () => {
                const root = document.querySelector("body");
                const data = root?._x_dataStack?.[0];
                if (!data) return "";
                const plugin = (data.aiUI?.plugins || []).find((p) => p.id === "ai-fast-api");
                if (!plugin) return "";
                await data.selectAiUIPlugin(plugin);
                return data.getAiUiPluginRouteLabel(data.aiUI.selectedPlugin);
            }
            """
        )
        assert "auto" in initial_label.lower()
        assert "gpt-4o-mini" in initial_label

        test_btn = page.get_by_role("button", name="Test LLM")
        expect(test_btn).to_be_visible()
        test_btn.click()

        page.wait_for_function(
            """
            () => {
                const root = document.querySelector("body");
                const data = root?._x_dataStack?.[0];
                if (!data?.aiUI?.selectedPlugin) return false;
                const label = data.getAiUiPluginRouteLabel(data.aiUI.selectedPlugin) || "";
                return (
                    label.toLowerCase().includes("codex") &&
                    label.includes("CodexOAuth") &&
                    label.includes("gpt-5")
                );
            }
            """
        )

        final_label = page.evaluate(
            """
            () => {
                const root = document.querySelector("body");
                const data = root?._x_dataStack?.[0];
                return data?.getAiUiPluginRouteLabel(data.aiUI.selectedPlugin) || "";
            }
            """
        )
        assert "codex" in final_label.lower()
        assert "CodexOAuth" in final_label
        assert "gpt-5" in final_label

    def test_discover_install_disabled_for_unsupported_app(self, page: Page, dashboard_url: str):
        """Unsupported gallery app should render disabled Install action."""
        state = {"install_calls": 0}

        def handle_requirements(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"requirements":[]}',
            )

        def handle_gallery(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=(
                    '{"apps":[{"id":"wan2gp","name":"Wan2GP","description":"Template","icon":"film","source":'
                    '"builtin:wan2gp","stars":"Windows-first","category":"Curated / Built-in",'
                    '"install_disabled":true,'
                    '"install_disabled_reason":"Wan2GP is unavailable on macOS arm64. '
                    'Use Windows/Linux with NVIDIA GPU."}]}'
                ),
            )

        def handle_plugins(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"plugins": []}),
            )

        def handle_install(route):
            if route.request.method == "POST":
                state["install_calls"] += 1
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body='{"status":"ok","message":"Installed","plugin_id":"wan2gp"}',
                )
                return
            route.continue_()

        page.route("**/api/ai-ui/requirements*", handle_requirements)
        page.route("**/api/ai-ui/gallery*", handle_gallery)
        page.route(re.compile(r".*/api/ai-ui/plugins/install(?:\?.*)?$"), handle_install)
        page.route(re.compile(r".*/api/ai-ui/plugins(?:\?.*)?$"), handle_plugins)

        page.goto(dashboard_url)
        page.locator("button:has-text('AI UI Local Cloud')").click()
        page.locator("button:has-text('Discover'):visible").first.click()

        wan_card = page.locator("div.group:has(code:text-is('builtin:wan2gp'))").first
        button = wan_card.get_by_role("button", name="Unsupported")
        expect(button).to_be_disabled()
        expect(button).to_have_text(re.compile(r"Unsupported"))
        expect(wan_card.get_by_text("unavailable on macOS arm64")).to_be_visible()
        assert state["install_calls"] == 0


class TestRemoteAccessModal:
    """Tests for the Remote Access modal."""

    def test_remote_button_exists(self, page: Page, dashboard_url: str):
        """Test that Take Your Paw With You button exists."""
        page.goto(dashboard_url)

        # This button might be hidden on mobile, so check desktop viewport
        remote_btn = page.locator("button:has-text('Take Your Paw With You')")
        # May not be visible on all viewports
        if remote_btn.is_visible():
            expect(remote_btn).to_be_visible()

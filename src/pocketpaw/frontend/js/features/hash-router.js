/**
 * PocketPaw - Hash Router Feature Module
 *
 * Created: 2026-02-12
 * Hash-based URL routing for view state persistence across page refreshes
 * and browser back/forward navigation.
 *
 * Route table:
 *   #/chat           → view = 'chat'
 *   #/chat/{id}      → view = 'chat', selectSession(id)
 *   #/activity       → view = 'activity'
 *   #/terminal       → view = 'terminal'
 *   #/crew           → view = 'missions', crewTab = 'tasks'
 *   #/crew/projects  → view = 'missions', crewTab = 'projects'
 *   #/project/{id}   → view = 'missions', crewTab = 'projects', selectProject(id)
 *   #/ai-ui          → view = 'ai-ui', aiUI.view = 'home'
 *   #/ai-ui/plugins  → view = 'ai-ui', aiUI.view = 'plugins'
 *   #/ai-ui/discover → view = 'ai-ui', aiUI.view = 'discover'
 *   #/ai-ui/shell    → view = 'ai-ui', aiUI.view = 'shell'
 *   #/ai-ui/api-docs → view = 'ai-ui', aiUI.view = 'api-docs'
 *   #/ai-ui/plugin/{id} → view = 'ai-ui', aiUI.view = 'plugin-detail', selectAiUIPlugin(id)
 *
 * State:
 *   _hashRouterInitialized, _suppressHashChange
 *
 * Methods:
 *   initHashRouter, navigateToView, updateHash, _parseHash, _applyRoute
 */

window.PocketPaw = window.PocketPaw || {};

window.PocketPaw.HashRouter = {
  name: "HashRouter",

  getState() {
    return {
      _hashRouterInitialized: false,
      _suppressHashChange: false,
    };
  },

  getMethods() {
    return {
      /**
       * Initialize hash router — parse initial hash and listen for changes.
       * Called from app.js init() after WebSocket setup.
       */
      initHashRouter() {
        if (this._hashRouterInitialized) return;
        this._hashRouterInitialized = true;

        // Listen for browser back/forward
        window.addEventListener("hashchange", () => {
          if (this._suppressHashChange) {
            this._suppressHashChange = false;
            return;
          }
          const route = this._parseHash();
          this._applyRoute(route);
        });

        // Apply initial hash on page load
        const hash = window.location.hash;
        if (hash && hash.length > 1) {
          const route = this._parseHash();
          this._applyRoute(route);
        }
      },

      /**
       * Navigate to a view and update the hash.
       * Replaces direct `view = 'xxx'` assignments in the top bar.
       */
      navigateToView(viewName) {
        this.view = viewName;

        // Load MC data when switching to Crew
        if (viewName === "missions") {
          this.loadMCData();
        }

        // Init AI UI data when switching to AI UI
        if (viewName === "ai-ui" && this.initAiUI) {
          this.initAiUI();
        }

        // Map view names to hash routes (ai-ui uses base hash; sub-routes via updateAiUIHash)
        const hashMap = {
          chat: "#/chat",
          activity: "#/activity",
          terminal: "#/terminal",
          missions: "#/crew",
          "anti-browser": "#/anti-browser",
          "ai-ui": "#/ai-ui",
        };
        this.updateHash(hashMap[viewName] ?? "#/chat");
      },

      /**
       * Navigate to chat with an optional session id route.
       */
      navigateToChatSession(sessionId = null) {
        this.view = "chat";
        if (sessionId) {
          this.updateHash(`#/chat/${encodeURIComponent(sessionId)}`);
          return;
        }
        this.updateHash("#/chat");
      },

      /**
       * Update the URL hash without triggering the hashchange handler.
       */
      updateHash(hash) {
        if (window.location.hash === hash) return;
        this._suppressHashChange = true;
        window.location.hash = hash;
      },

      /**
       * Parse the current URL hash into a route object.
       */
      _parseHash() {
        const hash = window.location.hash || "";
        // Strip leading #
        const path = hash.startsWith("#") ? hash.substring(1) : hash;
        // Strip leading /
        const clean = path.startsWith("/") ? path.substring(1) : path;
        const parts = clean.split("/");

        // Default route
        const route = { view: "chat", crewTab: null, projectId: null, sessionId: null };

        if (parts[0] === "chat") {
          route.view = "chat";
          if (parts[1]) {
            try {
              route.sessionId = decodeURIComponent(parts[1]);
            } catch (_) {
              route.sessionId = parts[1];
            }
          }
        } else if (parts[0] === "activity") {
          route.view = "activity";
        } else if (parts[0] === "terminal") {
          route.view = "terminal";
        } else if (parts[0] === "anti-browser") {
          route.view = "anti-browser";
        } else if (parts[0] === "ai-ui") {
          route.view = "ai-ui";
          route.aiUIView = parts[1] || "home";
          if (parts[1] === "plugin" && parts[2]) {
            route.aiUIView = "plugin-detail";
            route.aiUIPluginId = parts[2];
            if (["overview", "web", "api"].includes(parts[3])) {
              route.aiUIPluginTab = parts[3];
            }
          } else if (
            ["plugins", "discover", "shell", "api-docs"].includes(parts[1])
          ) {
            route.aiUIView = parts[1];
          }
        } else if (parts[0] === "crew") {
          route.view = "missions";
          route.crewTab = parts[1] === "projects" ? "projects" : "tasks";
        } else if (parts[0] === "project" && parts[1]) {
          route.view = "missions";
          route.crewTab = "projects";
          route.projectId = parts[1];
        }

        return route;
      },

      /**
       * Apply a parsed route to the Alpine state.
       */
      _applyRoute(route) {
        this.view = route.view;

        if (route.view === "chat") {
          if (route.sessionId && this.selectSession) {
            this.selectSession(route.sessionId, { syncHash: false });
          }
        } else if (route.view === "missions") {
          this.loadMCData();

          if (route.crewTab) {
            this.missionControl.crewTab = route.crewTab;
          }

          if (route.crewTab === "projects") {
            this.loadProjects();
          }

          // Deferred project selection — wait for projects to load
          if (route.projectId) {
            this._selectProjectById(route.projectId);
          }
        } else if (route.view === "anti-browser") {
          if (this.initAntiBrowser) {
            this.initAntiBrowser();
          }
        } else if (route.view === "ai-ui") {
          if (this.initAiUI) {
            this.initAiUI();
          }
          this.aiUI.view = route.aiUIView || "home";
          if (route.aiUIView === "discover" && this.fetchGallery) {
            this.fetchGallery();
          }
          if (route.aiUIPluginId) {
            this.aiUI.pluginDetailTab =
              route.aiUIPluginTab && ["overview", "web", "api"].includes(route.aiUIPluginTab)
                ? route.aiUIPluginTab
                : "web";
            this._selectAiUIPluginById(route.aiUIPluginId);
          }
        }

        this.$nextTick(() => {
          if (window.refreshIcons) window.refreshIcons();
        });
      },

      /**
       * Select an AI UI plugin by ID, waiting for plugins to load if needed.
       */
      async _selectAiUIPluginById(pluginId) {
        let plugin = this.aiUI.plugins.find((p) => p.id === pluginId);
        if (plugin) {
          this.selectAiUIPlugin(plugin);
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, 500));
        plugin = this.aiUI.plugins.find((p) => p.id === pluginId);
        if (plugin) {
          this.selectAiUIPlugin(plugin);
          return;
        }
        try {
          const res = await fetch(`/api/ai-ui/plugins/${pluginId}`);
          if (res.ok) {
            const data = await res.json();
            if (data.plugin) {
              this.aiUI.selectedPlugin = data.plugin;
              this.aiUI.view = "plugin-detail";
              this.$nextTick(() => {
                if (window.refreshIcons) window.refreshIcons();
              });
            }
          }
        } catch (e) {
          console.error("Failed to load plugin from hash:", e);
        }
      },

      /**
       * Update hash for AI UI sub-navigation. Call from setAiUIView / selectAiUIPlugin.
       */
      updateAiUIHash(subView, pluginId = null, tab = null) {
        if (pluginId) {
          const t =
            tab && ["overview", "web", "api"].includes(tab)
              ? tab
              : this.aiUI.pluginDetailTab || "web";
          this.updateHash(`#/ai-ui/plugin/${pluginId}/${t}`);
        } else {
          const map = {
            home: "#/ai-ui",
            plugins: "#/ai-ui/plugins",
            discover: "#/ai-ui/discover",
            shell: "#/ai-ui/shell",
            "api-docs": "#/ai-ui/api-docs",
          };
          this.updateHash(map[subView] ?? "#/ai-ui");
        }
      },

      /**
       * Select a project by ID, waiting for the project list to load if needed.
       */
      async _selectProjectById(projectId) {
        // Try immediate match
        let project = this.missionControl.projects.find(
          (p) => p.id === projectId,
        );
        if (project) {
          this.selectProject(project);
          return;
        }

        // Projects may not be loaded yet — wait a bit and retry
        await new Promise((resolve) => setTimeout(resolve, 500));

        // Try from sidebar projects (may have loaded separately)
        project = this.sidebarProjects.find((p) => p.id === projectId);
        if (!project) {
          project = this.missionControl.projects.find(
            (p) => p.id === projectId,
          );
        }

        if (project) {
          this.selectProject(project);
        } else {
          // Last resort: fetch directly
          try {
            const res = await fetch(
              `/api/deep-work/projects/${projectId}/plan`,
            );
            if (res.ok) {
              const data = await res.json();
              if (data.project) {
                this.selectProject(data.project);
              }
            }
          } catch (e) {
            console.error("Failed to load project from hash:", e);
          }
        }
      },
    };
  },
};

window.PocketPaw.Loader.register("HashRouter", window.PocketPaw.HashRouter);

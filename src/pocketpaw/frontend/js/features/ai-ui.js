/**
 * PocketPaw - AI UI Feature Module
 *
 * Created: 2026-02-24
 * Pinokio-inspired local AI app launcher.
 * Manages system requirements, plugins at ./plugins,
 * 1-click launch, and shell command execution.
 *
 * State:
 *   aiUI.{view, requirements, plugins, selectedPlugin, installing, logs, shell}
 *
 * Methods:
 *   initAiUI, fetchRequirements, installRequirement, fetchPlugins,
 *   installPlugin, launchPlugin, stopPlugin, removePlugin,
 *   runShellCommand, clearShellOutput
 */

window.PocketPaw = window.PocketPaw || {};

window.PocketPaw.AiUI = {
  name: "AiUI",

  getState() {
    return {
      aiUI: {
        view: "home", // 'home' | 'discover' | 'plugins' | 'shell' | 'plugin-detail'
        loading: false,
        search: "",

        // System requirements
        requirements: [],
        requirementsLoading: false,
        installingReq: null,

        // Plugins
        plugins: [],
        pluginsLoading: false,
        selectedPlugin: null,
        installingPlugin: null,
        launchingPlugin: null,

        // Plugin install form
        installForm: {
          url: "",
          installing: false,
        },

        // Shell
        shell: {
          command: "",
          output: [],
          running: false,
          history: [],
          historyIndex: -1,
        },

        // Logs for running apps
        logs: {},

        // Discover / gallery
        gallery: [],
        galleryLoading: false,
      },
    };
  },

  getMethods() {
    return {
      // ==================== Init ====================

      async initAiUI() {
        if (this.aiUI.requirements.length === 0) {
          await this.fetchRequirements();
        }
        if (this.aiUI.plugins.length === 0) {
          await this.fetchPlugins();
        }
        this.$nextTick(() => {
          if (window.refreshIcons) window.refreshIcons();
        });
      },

      // ==================== System Requirements ====================

      async fetchRequirements() {
        this.aiUI.requirementsLoading = true;
        try {
          const res = await fetch("/api/ai-ui/requirements");
          if (res.ok) {
            const data = await res.json();
            this.aiUI.requirements = data.requirements || [];
          }
        } catch (e) {
          console.error("Failed to load requirements:", e);
        } finally {
          this.aiUI.requirementsLoading = false;
          this.$nextTick(() => {
            if (window.refreshIcons) window.refreshIcons();
          });
        }
      },

      async installRequirement(reqId) {
        this.aiUI.installingReq = reqId;
        try {
          const res = await fetch(`/api/ai-ui/requirements/${reqId}/install`, {
            method: "POST",
          });
          if (res.ok) {
            const data = await res.json();
            this.showToast(
              data.message || `${reqId} is ready to use!`,
              "success",
            );
            await this.fetchRequirements();
          } else {
            const err = await res.json();
            this.showToast(
              err.detail || `Couldn't set up ${reqId}. Please try again.`,
              "error",
            );
          }
        } catch (e) {
          console.error("Install error:", e);
          this.showToast(
            `Couldn't set up ${reqId}. Check your connection and try again.`,
            "error",
          );
        } finally {
          this.aiUI.installingReq = null;
        }
      },

      requirementsInstalled() {
        return this.aiUI.requirements.filter((r) => r.installed).length;
      },

      requirementsTotal() {
        return this.aiUI.requirements.length;
      },

      // ==================== Plugins ====================

      async fetchPlugins() {
        this.aiUI.pluginsLoading = true;
        try {
          const res = await fetch("/api/ai-ui/plugins");
          if (res.ok) {
            const data = await res.json();
            this.aiUI.plugins = data.plugins || [];
          }
        } catch (e) {
          console.error("Failed to load plugins:", e);
        } finally {
          this.aiUI.pluginsLoading = false;
          this.$nextTick(() => {
            if (window.refreshIcons) window.refreshIcons();
          });
        }
      },

      filteredAiUIPlugins() {
        const q = this.aiUI.search.toLowerCase();
        if (!q) return this.aiUI.plugins;
        return this.aiUI.plugins.filter(
          (p) =>
            p.name.toLowerCase().includes(q) ||
            (p.description || "").toLowerCase().includes(q),
        );
      },

      async selectAiUIPlugin(plugin) {
        this.aiUI.selectedPlugin = plugin;
        this.aiUI.view = "plugin-detail";
        // Fetch latest plugin details
        try {
          const res = await fetch(`/api/ai-ui/plugins/${plugin.id}`);
          if (res.ok) {
            const data = await res.json();
            this.aiUI.selectedPlugin = data.plugin;
          }
        } catch (e) {
          console.error("Failed to load plugin details:", e);
        }
        this.$nextTick(() => {
          if (window.refreshIcons) window.refreshIcons();
        });
      },

      async installAiUIPlugin() {
        const url = this.aiUI.installForm.url.trim();
        if (!url) {
          this.showToast("Please enter a Git URL or path", "error");
          return;
        }

        this.aiUI.installForm.installing = true;
        try {
          const res = await fetch("/api/ai-ui/plugins/install", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ source: url }),
          });
          if (res.ok) {
            const data = await res.json();
            this.showToast(
              data.message || "Plugin installed successfully!",
              "success",
            );
            this.aiUI.installForm.url = "";
            await this.fetchPlugins();
          } else {
            const err = await res.json();
            this.showToast(err.detail || "Installation failed", "error");
          }
        } catch (e) {
          console.error("Plugin install error:", e);
          this.showToast("Installation failed", "error");
        } finally {
          this.aiUI.installForm.installing = false;
        }
      },

      async launchAiUIPlugin(pluginId) {
        this.aiUI.launchingPlugin = pluginId;
        try {
          const res = await fetch(`/api/ai-ui/plugins/${pluginId}/launch`, {
            method: "POST",
          });
          if (res.ok) {
            const data = await res.json();
            this.showToast(data.message || "App launched!", "success");
            await this.fetchPlugins();
            // Update selected plugin if viewing detail
            if (this.aiUI.selectedPlugin?.id === pluginId) {
              const plugin = this.aiUI.plugins.find((p) => p.id === pluginId);
              if (plugin) this.aiUI.selectedPlugin = plugin;
            }
          } else {
            const err = await res.json();
            this.showToast(err.detail || "Launch failed", "error");
          }
        } catch (e) {
          console.error("Launch error:", e);
          this.showToast("Launch failed", "error");
        } finally {
          this.aiUI.launchingPlugin = null;
        }
      },

      async stopAiUIPlugin(pluginId) {
        try {
          const res = await fetch(`/api/ai-ui/plugins/${pluginId}/stop`, {
            method: "POST",
          });
          if (res.ok) {
            this.showToast("App stopped", "info");
            await this.fetchPlugins();
            if (this.aiUI.selectedPlugin?.id === pluginId) {
              const plugin = this.aiUI.plugins.find((p) => p.id === pluginId);
              if (plugin) this.aiUI.selectedPlugin = plugin;
            }
          } else {
            const err = await res.json();
            this.showToast(err.detail || "Failed to stop app", "error");
          }
        } catch (e) {
          this.showToast("Failed to stop app", "error");
        }
      },

      async removeAiUIPlugin(pluginId) {
        try {
          const res = await fetch(`/api/ai-ui/plugins/${pluginId}`, {
            method: "DELETE",
          });
          if (res.ok) {
            this.showToast("Plugin removed", "info");
            this.aiUI.plugins = this.aiUI.plugins.filter(
              (p) => p.id !== pluginId,
            );
            if (this.aiUI.selectedPlugin?.id === pluginId) {
              this.aiUI.selectedPlugin = null;
              this.aiUI.view = "plugins";
            }
          } else {
            const err = await res.json();
            this.showToast(err.detail || "Failed to remove plugin", "error");
          }
        } catch (e) {
          this.showToast("Failed to remove plugin", "error");
        }
      },

      async fetchAiUIPluginLogs(pluginId) {
        try {
          const res = await fetch(`/api/ai-ui/plugins/${pluginId}/logs`);
          if (res.ok) {
            const data = await res.json();
            this.aiUI.logs[pluginId] = data.logs || [];
          }
        } catch (e) {
          console.error("Failed to fetch logs:", e);
        }
      },

      // ==================== Shell ====================

      async runShellCommand() {
        const cmd = this.aiUI.shell.command.trim();
        if (!cmd) return;

        this.aiUI.shell.running = true;
        this.aiUI.shell.history.unshift(cmd);
        if (this.aiUI.shell.history.length > 50) {
          this.aiUI.shell.history.pop();
        }
        this.aiUI.shell.historyIndex = -1;

        this.aiUI.shell.output.push({
          type: "command",
          text: `$ ${cmd}`,
          ts: new Date().toISOString(),
        });

        try {
          const res = await fetch("/api/ai-ui/shell", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ command: cmd }),
          });
          if (res.ok) {
            const data = await res.json();
            this.aiUI.shell.output.push({
              type: data.exit_code === 0 ? "stdout" : "stderr",
              text: data.output || "(no output)",
              exit_code: data.exit_code,
              ts: new Date().toISOString(),
            });
          } else {
            const err = await res.json();
            this.aiUI.shell.output.push({
              type: "stderr",
              text: err.detail || "Command failed",
              ts: new Date().toISOString(),
            });
          }
        } catch (e) {
          this.aiUI.shell.output.push({
            type: "stderr",
            text: `Error: ${e.message}`,
            ts: new Date().toISOString(),
          });
        } finally {
          this.aiUI.shell.running = false;
          this.aiUI.shell.command = "";
          // Scroll to bottom
          this.$nextTick(() => {
            const el = document.getElementById("ai-ui-shell-output");
            if (el) el.scrollTop = el.scrollHeight;
          });
        }
      },

      shellHistoryUp() {
        if (this.aiUI.shell.history.length === 0) return;
        const idx = this.aiUI.shell.historyIndex + 1;
        if (idx < this.aiUI.shell.history.length) {
          this.aiUI.shell.historyIndex = idx;
          this.aiUI.shell.command = this.aiUI.shell.history[idx];
        }
      },

      shellHistoryDown() {
        if (this.aiUI.shell.historyIndex <= 0) {
          this.aiUI.shell.historyIndex = -1;
          this.aiUI.shell.command = "";
          return;
        }
        this.aiUI.shell.historyIndex--;
        this.aiUI.shell.command =
          this.aiUI.shell.history[this.aiUI.shell.historyIndex];
      },

      clearShellOutput() {
        this.aiUI.shell.output = [];
      },

      // ==================== Navigation ====================

      setAiUIView(v) {
        this.aiUI.view = v;
        if (v === "plugins") this.fetchPlugins();
        this.$nextTick(() => {
          if (window.refreshIcons) window.refreshIcons();
        });
      },

      // ==================== Gallery (future) ====================

      async fetchGallery() {
        this.aiUI.galleryLoading = true;
        try {
          const res = await fetch("/api/ai-ui/gallery");
          if (res.ok) {
            const data = await res.json();
            this.aiUI.gallery = data.apps || [];
          }
        } catch (e) {
          console.error("Failed to load gallery:", e);
        } finally {
          this.aiUI.galleryLoading = false;
        }
      },
    };
  },
};

window.PocketPaw.Loader.register("AiUI", window.PocketPaw.AiUI);

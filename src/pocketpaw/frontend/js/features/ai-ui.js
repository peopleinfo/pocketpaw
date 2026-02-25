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

        // Plugin detail tab (persisted in URL: overview | web | api)
        pluginDetailTab: "web",

        // Plugin config modal (provider, model, etc.)
        configModalOpen: false,
        configModalPluginId: null,
        pluginConfig: {},
        pluginConfigDraft: {},
        configModels: [], // from API when plugin running
        configProviders: [], // from API when plugin running
        savingConfig: false,
        testingConnection: false,
        connectionTestResult: null,
        detailTestResult: null,
        testingDetailConnection: false,
      },
    };
  },

  getMethods() {
    return {
      // ==================== Init ====================

      async initAiUI() {
        // Bridge for nested native chat (set early so it exists before async work)
        const self = this;
        window._aiUiChatBridge = {
          getPluginId: () => self.aiUI?.selectedPlugin?.id,
          getPluginName: () => self.aiUI?.selectedPlugin?.name || 'Plugin',
          send: (id, msgs) => self.sendAiUIChatMessage(id || self.aiUI?.selectedPlugin?.id, msgs),
          load: (id) => self.loadAiUIChatHistory(id || self.aiUI?.selectedPlugin?.id),
          save: (id, msgs) =>
            self.saveAiUIChatHistory(id || self.aiUI?.selectedPlugin?.id, msgs),
        };
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

      copyConfigValue(value, label = "Copied") {
        const text = (value || "").toString().trim();
        if (!text) return;
        navigator.clipboard?.writeText(text).then(
          () => this.showToast?.(`${label} copied`, "success"),
          () => {}
        );
      },

      setPluginDetailTab(tab) {
        if (!["overview", "web", "api"].includes(tab)) return;
        this.aiUI.pluginDetailTab = tab;
        if (this.updateAiUIHash && this.aiUI.selectedPlugin?.id) {
          this.updateAiUIHash("plugin-detail", this.aiUI.selectedPlugin.id, tab);
        }
      },

      async selectAiUIPlugin(plugin) {
        this.aiUI.detailTestResult = null;
        this.aiUI.selectedPlugin = plugin;
        this.aiUI.view = "plugin-detail";
        if (this.updateAiUIHash) {
          this.updateAiUIHash("plugin-detail", plugin.id);
        }
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

      async installAiUIPluginFromZip(event) {
        const file = event?.target?.files?.[0];
        if (!file || !file.name.toLowerCase().endsWith(".zip")) {
          if (file) this.showToast("Please upload a .zip file", "error");
          event.target.value = "";
          return;
        }

        this.aiUI.installForm.installing = true;
        try {
          const formData = new FormData();
          formData.append("file", file);
          const res = await fetch("/api/ai-ui/plugins/install", {
            method: "POST",
            body: formData,
          });
          if (res.ok) {
            const data = await res.json();
            this.showToast(
              data.message || "Plugin installed successfully!",
              "success",
            );
            await this.fetchPlugins();
            if (this.aiUI.selectedPlugin?.id === data.plugin_id) {
              const plugin = this.aiUI.plugins.find((p) => p.id === data.plugin_id);
              if (plugin) this.aiUI.selectedPlugin = plugin;
            }
            this.$nextTick(() => {
              if (window.refreshIcons) window.refreshIcons();
            });
          } else {
            const err = await res.json();
            this.showToast(err.detail || "Installation failed", "error");
          }
        } catch (e) {
          console.error("Plugin install from zip error:", e);
          this.showToast("Installation failed", "error");
        } finally {
          this.aiUI.installForm.installing = false;
          event.target.value = "";
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
              if (this.updateAiUIHash) {
                this.updateAiUIHash("plugins");
              }
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
        if (this.updateAiUIHash) {
          this.updateAiUIHash(v);
        }
        this.$nextTick(() => {
          if (window.refreshIcons) window.refreshIcons();
        });
      },

      backToAiUIPlugins() {
        this.aiUI.detailTestResult = null;
        this.aiUI.view = "plugins";
        this.aiUI.selectedPlugin = null;
        if (this.updateAiUIHash) {
          this.updateAiUIHash("plugins");
        }
        this.fetchPlugins();
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

      // ==================== Plugin Config ====================

      async openPluginConfigModal(pluginId) {
        this.aiUI.configModalPluginId = pluginId;
        this.aiUI.configModalOpen = true;
        this.aiUI.configModels = [];
        this.aiUI.configProviders = [];
        const aiFastApiDefaults = {
          LLM_BACKEND: "g4f",
          G4F_PROVIDER: "auto",
          G4F_MODEL: "gpt-4o-mini",
          DEBUG: "true",
          HOST: "0.0.0.0",
          PORT: "8000",
        };
        try {
          const res = await fetch(`/api/ai-ui/plugins/${pluginId}/config`);
          if (res.ok) {
            const data = await res.json();
            this.aiUI.pluginConfig = data.config || {};
            this.aiUI.pluginConfigDraft = {
              ...aiFastApiDefaults,
              ...this.aiUI.pluginConfig,
            };
          } else {
            this.aiUI.pluginConfig = {};
            this.aiUI.pluginConfigDraft = { ...aiFastApiDefaults };
          }
        } catch (e) {
          console.error("Failed to load plugin config:", e);
          this.aiUI.pluginConfig = {};
          this.aiUI.pluginConfigDraft = { ...aiFastApiDefaults };
        }
        if (pluginId === "ai-fast-api") {
          const host = this.aiUI.pluginConfigDraft.HOST || "0.0.0.0";
          const port = this.aiUI.pluginConfigDraft.PORT || "8000";
          const params = new URLSearchParams();
          if (host && host !== "0.0.0.0") params.set("host", host);
          if (port) params.set("port", String(port));
          const qs = params.toString() ? "?" + params.toString() : "";
          try {
            const [modelsRes, providersRes] = await Promise.all([
              fetch(`/api/ai-ui/plugins/${pluginId}/models${qs}`),
              fetch(`/api/ai-ui/plugins/${pluginId}/providers${qs}`),
            ]);
            if (modelsRes.ok) {
              const data = await modelsRes.json();
              const models = data.models || [];
              const savedModel = this.aiUI.pluginConfig?.G4F_MODEL || this.aiUI.pluginConfigDraft.G4F_MODEL;
              if (savedModel && !models.some((m) => m.id === savedModel)) {
                models.unshift({ id: savedModel });
              }
              this.aiUI.configModels = models;
              // Re-apply saved model so select binding picks it up after async options load
              if (savedModel) {
                this.aiUI.pluginConfigDraft.G4F_MODEL = savedModel;
              }
              this.$nextTick(() => {
                if (savedModel) this.aiUI.pluginConfigDraft.G4F_MODEL = savedModel;
              });
            }
            if (providersRes.ok) {
              const data = await providersRes.json();
              const providers = data.providers || [];
              const savedProvider =
                this.aiUI.pluginConfig?.G4F_PROVIDER || this.aiUI.pluginConfigDraft.G4F_PROVIDER;
              if (savedProvider && savedProvider !== "auto" && !providers.some((p) => p.id === savedProvider)) {
                providers.unshift({ id: savedProvider });
              }
              this.aiUI.configProviders = providers;
              if (savedProvider) {
                this.aiUI.pluginConfigDraft.G4F_PROVIDER = savedProvider;
              }
              this.$nextTick(() => {
                if (savedProvider) this.aiUI.pluginConfigDraft.G4F_PROVIDER = savedProvider;
              });
            }
          } catch (_e) {
            // Plugin may not be running
          }
        }
        this.$nextTick(() => {
          if (window.refreshIcons) window.refreshIcons();
        });
      },

      closePluginConfigModal() {
        this.aiUI.configModalOpen = false;
        this.aiUI.configModalPluginId = null;
        this.aiUI.pluginConfig = {};
        this.aiUI.pluginConfigDraft = {};
        this.aiUI.configModels = [];
        this.aiUI.configProviders = [];
        this.aiUI.connectionTestResult = null;
      },

      async testPluginConnection() {
        const pluginId = this.aiUI.configModalPluginId;
        if (!pluginId) return;
        this.aiUI.testingConnection = true;
        this.aiUI.connectionTestResult = null;
        try {
          const host = this.aiUI.pluginConfigDraft.HOST;
          const port = this.aiUI.pluginConfigDraft.PORT;
          const body = {};
          if (host) body.host = host;
          if (port) body.port = parseInt(port, 10) || port;
          const res = await fetch(`/api/ai-ui/plugins/${pluginId}/test-connection`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
          const data = await res.json();
          this.aiUI.connectionTestResult = data;
          if (data.ok) {
            this.showToast(data.message || "Connection OK", "success");
          } else {
            this.showToast(data.message || "Connection failed", "error");
          }
        } catch (e) {
          console.error("Test connection error:", e);
          this.aiUI.connectionTestResult = { ok: false, message: "Request failed" };
          this.showToast("Test failed", "error");
        } finally {
          this.aiUI.testingConnection = false;
          this.$nextTick(() => {
            if (window.refreshIcons) window.refreshIcons();
          });
        }
      },

      async testPluginConnectionFromDetail() {
        const pluginId = this.aiUI.selectedPlugin?.id;
        if (!pluginId || pluginId !== "ai-fast-api") return;
        this.aiUI.testingDetailConnection = true;
        this.aiUI.detailTestResult = null;
        try {
          const res = await fetch(`/api/ai-ui/plugins/${pluginId}/test-connection`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: "{}",
          });
          const data = await res.json();
          this.aiUI.detailTestResult = data;
          if (data.ok) {
            this.showToast(data.message || "LLM connection OK", "success");
          } else {
            this.showToast(data.message || "LLM connection failed", "error");
          }
        } catch (e) {
          console.error("Test connection error:", e);
          this.aiUI.detailTestResult = { ok: false, message: "Request failed" };
          this.showToast("Test failed", "error");
        } finally {
          this.aiUI.testingDetailConnection = false;
          this.$nextTick(() => {
            if (window.refreshIcons) window.refreshIcons();
          });
        }
      },

      async savePluginConfig() {
        const pluginId = this.aiUI.configModalPluginId;
        if (!pluginId) return;
        this.aiUI.savingConfig = true;
        try {
          const res = await fetch(`/api/ai-ui/plugins/${pluginId}/config`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(this.aiUI.pluginConfigDraft),
          });
          if (res.ok) {
            const data = await res.json();
            this.aiUI.pluginConfig = data.config || this.aiUI.pluginConfigDraft;
            this.showToast(
              "Config saved. Restart the plugin for changes to take effect.",
              "success",
            );
            this.closePluginConfigModal();
            // Refresh selected plugin env
            if (this.aiUI.selectedPlugin?.id === pluginId) {
              const p = this.aiUI.plugins.find((x) => x.id === pluginId);
              if (p) {
                this.aiUI.selectedPlugin = { ...this.aiUI.selectedPlugin, env: data.config };
              }
            }
          } else {
            const err = await res.json();
            this.showToast(err.detail || "Failed to save config", "error");
          }
        } catch (e) {
          console.error("Config save error:", e);
          this.showToast("Failed to save config", "error");
        } finally {
          this.aiUI.savingConfig = false;
        }
      },

      hasPluginConfig(plugin) {
        return plugin && plugin.id === "ai-fast-api";
      },

      // ==================== Plugin Chat (AI Fast API) ====================

      async sendAiUIChatMessage(pluginId, messages) {
        const res = await fetch(`/api/ai-ui/plugins/${pluginId}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        const content =
          data?.choices?.[0]?.message?.content ?? "No response";
        return { content };
      },

      async loadAiUIChatHistory(pluginId) {
        const res = await fetch(`/api/ai-ui/plugins/${pluginId}/chat-history`);
        if (!res.ok) return [];
        const data = await res.json();
        return data.messages || [];
      },

      async saveAiUIChatHistory(pluginId, messages) {
        await fetch(`/api/ai-ui/plugins/${pluginId}/chat-history`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages }),
        });
      },
    };
  },
};

window.PocketPaw.Loader.register("AiUI", window.PocketPaw.AiUI);

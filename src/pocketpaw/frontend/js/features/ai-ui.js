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
        installingGalleryApp: null,

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
        codexAuthStatus: null,
        codexOauthSessionId: null,
        codexVerificationUri: "",
        codexUserCode: "",
        codexAuthPolling: false,
        qwenAuthStatus: null,
        qwenOauthSessionId: null,
        qwenVerificationUri: "",
        qwenUserCode: "",
        qwenAuthPolling: false,
        geminiAuthStatus: null,
        geminiOauthSessionId: null,
        geminiVerificationUri: "",
        geminiUserCode: "",
        geminiAuthPolling: false,
        localOllamaSetupInProgress: false,
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
        this.log?.(`[AI UI] Install requested: ${url}`, "info");
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
            this.log?.(
              `[AI UI] Install success: ${data.plugin_id || "unknown"} - ${data.message || "Plugin installed successfully"}`,
              "success",
            );
            this.aiUI.installForm.url = "";
            await this.fetchPlugins();
            if (data.plugin_id) {
              await this.openAiUIPlugin(data.plugin_id);
            }
          } else {
            const err = await res.json();
            this.showToast(err.detail || "Installation failed", "error");
            this.log?.(
              `[AI UI] Install failed: ${url} - ${err.detail || "Installation failed"}`,
              "error",
            );
          }
        } catch (e) {
          console.error("Plugin install error:", e);
          this.showToast("Installation failed", "error");
          this.log?.(`[AI UI] Install error: ${url} - ${e.message || e}`, "error");
        } finally {
          this.aiUI.installForm.installing = false;
        }
      },

      getAiUIPluginById(pluginId) {
        return this.aiUI.plugins.find((p) => p.id === pluginId) || null;
      },

      async openAiUIPlugin(pluginId) {
        if (!pluginId) return;

        let plugin = this.getAiUIPluginById(pluginId);
        if (!plugin) {
          await this.fetchPlugins();
          plugin = this.getAiUIPluginById(pluginId);
        }
        if (!plugin) {
          this.showToast("Plugin not found", "error");
          return;
        }

        if (plugin.status !== "running") {
          await this.launchAiUIPlugin(pluginId);
          await this.fetchPlugins();
          plugin = this.getAiUIPluginById(pluginId) || plugin;
        }

        await this.selectAiUIPlugin(plugin);
        this.setPluginDetailTab("web");
      },

      isGalleryAppInstalled(app) {
        return !!this.getAiUIPluginById(app?.id);
      },

      isGalleryInstallDisabled(app) {
        const plugin = this.getAiUIPluginById(app?.id);
        if (plugin) return false;
        return !!app?.install_disabled;
      },

      galleryInstallDisabledReason(app) {
        if (!this.isGalleryInstallDisabled(app)) return "";
        return app?.install_disabled_reason || "This app is not supported on your OS.";
      },

      galleryInstallLabel(app) {
        if (this.aiUI.installingGalleryApp === app?.id) return "Installing...";
        if (this.isGalleryInstallDisabled(app)) return "Unsupported";
        const plugin = this.getAiUIPluginById(app?.id);
        if (plugin) return plugin.status === "running" ? "Open" : "Start & Open";
        return "Install";
      },

      galleryActionIcon(app) {
        if (this.aiUI.installingGalleryApp === app?.id) return "loader-2";
        if (this.isGalleryInstallDisabled(app)) return "ban";
        const plugin = this.getAiUIPluginById(app?.id);
        if (!plugin) return "download";
        return plugin.status === "running" ? "external-link" : "play";
      },

      async installAiUIGalleryApp(app) {
        if (this.isGalleryInstallDisabled(app)) {
          const reason = this.galleryInstallDisabledReason(app);
          this.showToast(reason, "error");
          this.log?.(`[AI UI] Gallery install blocked: ${app?.id} - ${reason}`, "warning");
          return;
        }

        const source = (app?.source || "").trim();
        if (!source) {
          this.showToast("This app has no install source", "error");
          return;
        }

        const installed = this.getAiUIPluginById(app.id);
        if (installed) {
          await this.openAiUIPlugin(app.id);
          return;
        }

        this.aiUI.installingGalleryApp = app.id;
        this.log?.(`[AI UI] Gallery install requested: ${app.id}`, "info");
        try {
          const res = await fetch("/api/ai-ui/plugins/install", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ source }),
          });
          if (res.ok) {
            const data = await res.json();
            this.showToast(
              data.message || "Plugin installed successfully!",
              "success",
            );
            this.log?.(
              `[AI UI] Gallery install success: ${data.plugin_id || app.id} - ${data.message || "Plugin installed successfully"}`,
              "success",
            );
            await this.fetchPlugins();
            await this.fetchGallery();
            await this.openAiUIPlugin(data.plugin_id || app.id);
          } else {
            const err = await res.json();
            this.showToast(err.detail || "Installation failed", "error");
            this.log?.(
              `[AI UI] Gallery install failed: ${app.id} - ${err.detail || "Installation failed"}`,
              "error",
            );
          }
        } catch (e) {
          console.error("Gallery install error:", e);
          this.showToast("Installation failed", "error");
          this.log?.(`[AI UI] Gallery install error: ${app.id} - ${e.message || e}`, "error");
        } finally {
          this.aiUI.installingGalleryApp = null;
          this.$nextTick(() => {
            if (window.refreshIcons) window.refreshIcons();
          });
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
        this.log?.(`[AI UI] Zip install requested: ${file.name}`, "info");
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
            this.log?.(
              `[AI UI] Zip install success: ${data.plugin_id || file.name} - ${data.message || "Plugin installed successfully"}`,
              "success",
            );
            await this.fetchPlugins();
            if (data.plugin_id) {
              await this.openAiUIPlugin(data.plugin_id);
            } else if (this.aiUI.selectedPlugin?.id) {
              const plugin = this.aiUI.plugins.find((p) => p.id === this.aiUI.selectedPlugin.id);
              if (plugin) this.aiUI.selectedPlugin = plugin;
            }
            this.$nextTick(() => {
              if (window.refreshIcons) window.refreshIcons();
            });
          } else {
            const err = await res.json();
            this.showToast(err.detail || "Installation failed", "error");
            this.log?.(
              `[AI UI] Zip install failed: ${file.name} - ${err.detail || "Installation failed"}`,
              "error",
            );
          }
        } catch (e) {
          console.error("Plugin install from zip error:", e);
          this.showToast("Installation failed", "error");
          this.log?.(`[AI UI] Zip install error: ${file.name} - ${e.message || e}`, "error");
        } finally {
          this.aiUI.installForm.installing = false;
          event.target.value = "";
        }
      },

      async launchAiUIPlugin(pluginId) {
        this.aiUI.launchingPlugin = pluginId;
        this.log?.(`[AI UI] Launch requested: ${pluginId}`, "info");
        try {
          const res = await fetch(`/api/ai-ui/plugins/${pluginId}/launch`, {
            method: "POST",
          });
          if (res.ok) {
            const data = await res.json();
            this.showToast(data.message || "App launched!", "success");
            this.log?.(
              `[AI UI] Launch success: ${pluginId} - ${data.message || "App launched"}`,
              "success",
            );
            await this.fetchPlugins();
            await this.fetchAiUIPluginLogs(pluginId);
            const lines = this.aiUI.logs?.[pluginId] || [];
            if (lines.length > 0) {
              this.log?.(`[AI UI:${pluginId}] ${lines[lines.length - 1]}`, "info");
            }
            // Update selected plugin if viewing detail
            if (this.aiUI.selectedPlugin?.id === pluginId) {
              const plugin = this.aiUI.plugins.find((p) => p.id === pluginId);
              if (plugin) this.aiUI.selectedPlugin = plugin;
            }
          } else {
            const err = await res.json();
            this.showToast(err.detail || "Launch failed", "error");
            this.log?.(
              `[AI UI] Launch failed: ${pluginId} - ${err.detail || "Launch failed"}`,
              "error",
            );
            await this.fetchAiUIPluginLogs(pluginId);
            const lines = this.aiUI.logs?.[pluginId] || [];
            if (lines.length > 0) {
              this.log?.(`[AI UI:${pluginId}] ${lines[lines.length - 1]}`, "error");
            }
          }
        } catch (e) {
          console.error("Launch error:", e);
          this.showToast("Launch failed", "error");
          this.log?.(`[AI UI] Launch error: ${pluginId} - ${e.message || e}`, "error");
        } finally {
          this.aiUI.launchingPlugin = null;
        }
      },

      async stopAiUIPlugin(pluginId) {
        this.log?.(`[AI UI] Stop requested: ${pluginId}`, "info");
        try {
          const res = await fetch(`/api/ai-ui/plugins/${pluginId}/stop`, {
            method: "POST",
          });
          if (res.ok) {
            this.showToast("App stopped", "info");
            this.log?.(`[AI UI] Stop success: ${pluginId}`, "info");
            await this.fetchPlugins();
            if (this.aiUI.selectedPlugin?.id === pluginId) {
              const plugin = this.aiUI.plugins.find((p) => p.id === pluginId);
              if (plugin) this.aiUI.selectedPlugin = plugin;
            }
          } else {
            const err = await res.json();
            this.showToast(err.detail || "Failed to stop app", "error");
            this.log?.(
              `[AI UI] Stop failed: ${pluginId} - ${err.detail || "Failed to stop app"}`,
              "error",
            );
          }
        } catch (e) {
          this.showToast("Failed to stop app", "error");
          this.log?.(`[AI UI] Stop error: ${pluginId} - ${e.message || e}`, "error");
        }
      },

      async removeAiUIPlugin(pluginId) {
        this.log?.(`[AI UI] Remove requested: ${pluginId}`, "warning");
        try {
          const res = await fetch(`/api/ai-ui/plugins/${pluginId}`, {
            method: "DELETE",
          });
          if (res.ok) {
            this.showToast("Plugin removed", "info");
            this.log?.(`[AI UI] Remove success: ${pluginId}`, "warning");
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
            this.log?.(
              `[AI UI] Remove failed: ${pluginId} - ${err.detail || "Failed to remove plugin"}`,
              "error",
            );
          }
        } catch (e) {
          this.showToast("Failed to remove plugin", "error");
          this.log?.(`[AI UI] Remove error: ${pluginId} - ${e.message || e}`, "error");
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

      getOllamaBaseUrlDefault(deployment) {
        return deployment === "cloud" ? "https://ollama.com/v1" : "http://127.0.0.1:11434/v1";
      },

      inferOllamaDeployment(baseUrl) {
        const url = (baseUrl || "").trim().toLowerCase();
        return url.includes("ollama.com") ? "cloud" : "local";
      },

      normalizeOllamaDeployment(draft) {
        const inferred = this.inferOllamaDeployment(draft?.OLLAMA_BASE_URL);
        const deployment = (draft?.OLLAMA_DEPLOYMENT || "").toLowerCase();
        if (deployment === "cloud" || deployment === "local") return deployment;
        return inferred;
      },

      getOllamaDraftModel(draft, deploymentOverride = "") {
        if (!draft || typeof draft !== "object") return "llama3.1";
        const deployment = (deploymentOverride || this.normalizeOllamaDeployment(draft)).toLowerCase();
        const fallback = draft.OLLAMA_MODEL || draft.G4F_MODEL || "llama3.1";
        if (deployment === "cloud") {
          return draft.OLLAMA_CLOUD_MODEL || draft.OLLAMA_MODEL || fallback;
        }
        return draft.OLLAMA_LOCAL_MODEL || draft.OLLAMA_MODEL || fallback;
      },

      setOllamaDraftModel(draft, model, deploymentOverride = "") {
        if (!draft || typeof draft !== "object" || !model) return;
        const deployment = (deploymentOverride || this.normalizeOllamaDeployment(draft)).toLowerCase();
        if (deployment === "cloud") {
          draft.OLLAMA_CLOUD_MODEL = model;
        } else {
          draft.OLLAMA_LOCAL_MODEL = model;
        }
      },

      syncOllamaModelCompat(draft) {
        if (!draft || typeof draft !== "object") return;
        draft.OLLAMA_MODEL = this.getOllamaDraftModel(draft);
      },

      ensureOllamaConfigDraft(draft) {
        if (!draft || typeof draft !== "object") return;

        const fallbackModel = draft.OLLAMA_MODEL || draft.G4F_MODEL || "llama3.1";
        if (!draft.OLLAMA_LOCAL_MODEL) {
          draft.OLLAMA_LOCAL_MODEL = fallbackModel;
        }
        if (!draft.OLLAMA_CLOUD_MODEL) {
          draft.OLLAMA_CLOUD_MODEL = fallbackModel;
        }
        let deployment = this.normalizeOllamaDeployment(draft);
        draft.OLLAMA_DEPLOYMENT = deployment;
        if (!draft.OLLAMA_BASE_URL) {
          draft.OLLAMA_BASE_URL = this.getOllamaBaseUrlDefault(deployment);
        }
        if (draft.OLLAMA_API_KEY === undefined || draft.OLLAMA_API_KEY === null) {
          draft.OLLAMA_API_KEY = "";
        }
        this.syncOllamaModelCompat(draft);
      },

      async onAiFastApiBackendChange() {
        const backend = (this.aiUI.pluginConfigDraft.LLM_BACKEND || "").toLowerCase();
        if (backend === "ollama") {
          this.ensureOllamaConfigDraft(this.aiUI.pluginConfigDraft);
          return;
        }
        if (backend === "codex") {
          await this.fetchCodexAuthStatus(this.aiUI.configModalPluginId);
          return;
        }
        if (backend === "qwen") {
          await this.fetchQwenAuthStatus(this.aiUI.configModalPluginId);
          return;
        }
        if (backend === "gemini") {
          await this.fetchGeminiAuthStatus(this.aiUI.configModalPluginId);
        }
      },

      onOllamaDeploymentChange() {
        const draft = this.aiUI.pluginConfigDraft || {};
        const deployment = (draft.OLLAMA_DEPLOYMENT || "local").toLowerCase();
        const current = (draft.OLLAMA_BASE_URL || "").trim();
        const currentDefault = this.getOllamaBaseUrlDefault(this.inferOllamaDeployment(current));
        if (!current || current === currentDefault) {
          draft.OLLAMA_BASE_URL = this.getOllamaBaseUrlDefault(deployment);
        }
        this.syncOllamaModelCompat(draft);
      },

      async setupLocalOllamaForAiFastApi() {
        const pluginId = this.aiUI.configModalPluginId;
        if (pluginId !== "ai-fast-api") return;

        this.aiUI.localOllamaSetupInProgress = true;
        try {
          const res = await fetch(`/api/ai-ui/plugins/${pluginId}/ollama/local/setup`, {
            method: "POST",
          });
          const data = await res.json();
          if (!res.ok || data.ok === false) {
            this.showToast(data.detail || data.message || "Local Ollama setup failed", "error");
            return;
          }

          this.aiUI.pluginConfigDraft.OLLAMA_DEPLOYMENT = "local";
          this.aiUI.pluginConfigDraft.OLLAMA_BASE_URL =
            data.base_url || "http://127.0.0.1:11434/v1";
          this.syncOllamaModelCompat(this.aiUI.pluginConfigDraft);
          this.showToast(data.message || "Local Ollama is ready", "success");
          await this.fetchPlugins();
        } catch (e) {
          console.error("Local Ollama setup error:", e);
          this.showToast("Local Ollama setup failed", "error");
        } finally {
          this.aiUI.localOllamaSetupInProgress = false;
        }
      },

      async openPluginConfigModal(pluginId) {
        this.aiUI.configModalPluginId = pluginId;
        this.aiUI.configModalOpen = true;
        this.aiUI.configModels = [];
        this.aiUI.configProviders = [];
        const aiFastApiDefaults = {
          LLM_BACKEND: "g4f",
          G4F_PROVIDER: "auto",
          G4F_MODEL: "gpt-4o-mini",
          OLLAMA_LOCAL_MODEL: "llama3.1",
          OLLAMA_CLOUD_MODEL: "llama3.1",
          OLLAMA_MODEL: "llama3.1",
          OLLAMA_DEPLOYMENT: "local",
          OLLAMA_BASE_URL: "http://127.0.0.1:11434/v1",
          OLLAMA_API_KEY: "",
          CODEX_MODEL: "gpt-5",
          QWEN_MODEL: "qwen3-coder-plus",
          GEMINI_MODEL: "gemini-2.5-flash",
          AUTO_MAX_ROTATE_RETRY: "4",
          AUTO_ROTATE_BACKENDS: "g4f,ollama,codex,qwen,gemini",
          AUTO_G4F_MODEL: "gpt-4o-mini",
          AUTO_OLLAMA_MODEL: "llama3.1",
          AUTO_CODEX_MODEL: "gpt-5",
          AUTO_QWEN_MODEL: "qwen3-coder-plus",
          AUTO_GEMINI_MODEL: "gemini-2.5-flash",
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
        this.ensureOllamaConfigDraft(this.aiUI.pluginConfigDraft);
        if (pluginId === "ai-fast-api") {
          const backend = (this.aiUI.pluginConfigDraft.LLM_BACKEND || "g4f").toLowerCase();
          if (!["auto", "codex", "qwen", "gemini"].includes(backend)) {
            const host = this.aiUI.pluginConfigDraft.HOST || "0.0.0.0";
            const port = this.aiUI.pluginConfigDraft.PORT || "8000";
            const params = new URLSearchParams();
            if (host && host !== "0.0.0.0") params.set("host", host);
            if (port) params.set("port", String(port));
            const qs = params.toString() ? "?" + params.toString() : "";
            try {
              const modelsRes = await fetch(`/api/ai-ui/plugins/${pluginId}/models${qs}`);
              if (modelsRes.ok) {
                const data = await modelsRes.json();
                const models = data.models || [];
                const savedModel = backend === "ollama"
                  ? this.getOllamaDraftModel(this.aiUI.pluginConfigDraft)
                  : (
                      this.aiUI.pluginConfig?.G4F_MODEL || this.aiUI.pluginConfigDraft.G4F_MODEL
                    );
                if (backend === "ollama") {
                  const ollamaDraft = this.aiUI.pluginConfigDraft || {};
                  const candidateModels = [
                    ollamaDraft.OLLAMA_LOCAL_MODEL,
                    ollamaDraft.OLLAMA_CLOUD_MODEL,
                    ollamaDraft.OLLAMA_MODEL,
                    this.aiUI.pluginConfig?.OLLAMA_LOCAL_MODEL,
                    this.aiUI.pluginConfig?.OLLAMA_CLOUD_MODEL,
                    this.aiUI.pluginConfig?.OLLAMA_MODEL,
                  ].filter(Boolean);
                  for (const modelId of candidateModels) {
                    if (!models.some((m) => m.id === modelId)) {
                      models.unshift({ id: modelId });
                    }
                  }
                } else if (savedModel && !models.some((m) => m.id === savedModel)) {
                  models.unshift({ id: savedModel });
                }
                this.aiUI.configModels = models;
                if (savedModel) {
                  if (backend === "ollama") {
                    this.setOllamaDraftModel(this.aiUI.pluginConfigDraft, savedModel);
                    this.syncOllamaModelCompat(this.aiUI.pluginConfigDraft);
                  } else {
                    this.aiUI.pluginConfigDraft.G4F_MODEL = savedModel;
                  }
                }
                this.$nextTick(() => {
                  if (!savedModel) return;
                  if (backend === "ollama") {
                    this.setOllamaDraftModel(this.aiUI.pluginConfigDraft, savedModel);
                    this.syncOllamaModelCompat(this.aiUI.pluginConfigDraft);
                  } else {
                    this.aiUI.pluginConfigDraft.G4F_MODEL = savedModel;
                  }
                });
              }
              if (backend === "g4f") {
                const providersRes = await fetch(`/api/ai-ui/plugins/${pluginId}/providers${qs}`);
                if (providersRes.ok) {
                  const data = await providersRes.json();
                  const providers = data.providers || [];
                  const savedProvider =
                    this.aiUI.pluginConfig?.G4F_PROVIDER || this.aiUI.pluginConfigDraft.G4F_PROVIDER;
                  if (
                    savedProvider &&
                    savedProvider !== "auto" &&
                    !providers.some((p) => p.id === savedProvider)
                  ) {
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
              } else {
                this.aiUI.configProviders = [];
              }
            } catch (_e) {
              // Plugin may not be running
            }
          } else if (backend === "codex") {
            await this.fetchCodexAuthStatus(pluginId);
          } else if (backend === "qwen") {
            await this.fetchQwenAuthStatus(pluginId);
          } else if (backend === "gemini") {
            await this.fetchGeminiAuthStatus(pluginId);
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
        this.aiUI.codexAuthStatus = null;
        this.aiUI.codexOauthSessionId = null;
        this.aiUI.codexVerificationUri = "";
        this.aiUI.codexUserCode = "";
        this.aiUI.codexAuthPolling = false;
        this.aiUI.qwenAuthStatus = null;
        this.aiUI.qwenOauthSessionId = null;
        this.aiUI.qwenVerificationUri = "";
        this.aiUI.qwenUserCode = "";
        this.aiUI.qwenAuthPolling = false;
        this.aiUI.geminiAuthStatus = null;
        this.aiUI.geminiOauthSessionId = null;
        this.aiUI.geminiVerificationUri = "";
        this.aiUI.geminiUserCode = "";
        this.aiUI.geminiAuthPolling = false;
        this.aiUI.localOllamaSetupInProgress = false;
      },

      getAiUiPluginModel(plugin) {
        const env = plugin?.env || {};
        const backend = (env.LLM_BACKEND || "g4f").toLowerCase();
        if (backend === "auto") return env.AUTO_G4F_MODEL || env.G4F_MODEL || "gpt-4o-mini";
        if (backend === "ollama") return this.getOllamaDraftModel(env);
        if (backend === "codex") return env.CODEX_MODEL || "gpt-5";
        if (backend === "qwen") return env.QWEN_MODEL || "qwen3-coder-plus";
        if (backend === "gemini") return env.GEMINI_MODEL || "gemini-2.5-flash";
        return env.G4F_MODEL || "gpt-4o-mini";
      },

      getAiUiPluginProvider(plugin, backendOverride = "") {
        const env = plugin?.env || {};
        const backend = (backendOverride || env.LLM_BACKEND || "g4f").toLowerCase();
        if (backend === "codex") return "CodexOAuth";
        if (backend === "qwen") return "QwenOAuth";
        if (backend === "gemini") return "GeminiOAuth";
        if (backend === "ollama") {
          const deployment = (env.OLLAMA_DEPLOYMENT || this.inferOllamaDeployment(env.OLLAMA_BASE_URL))
            .toLowerCase();
          return deployment === "cloud" ? "Cloud Ollama" : "Local Ollama";
        }
        if (backend === "g4f") return env.G4F_PROVIDER || "auto";
        return "AutoRotate";
      },

      getAiUiPluginRouteLabel(plugin) {
        const env = plugin?.env || {};
        const configuredBackend = (env.LLM_BACKEND || "g4f").toLowerCase();
        const fallbackModel = this.getAiUiPluginModel(plugin);
        if (configuredBackend !== "auto") {
          const provider = this.getAiUiPluginProvider(plugin, configuredBackend);
          return `${configuredBackend} · ${provider} · ${fallbackModel}`;
        }

        const route = this.aiUI?.detailTestResult;
        if (
          route &&
          route.ok &&
          (route.requested_backend || "").toLowerCase() === "auto" &&
          route.selected_model
        ) {
          const backend = (route.selected_backend || "auto").toLowerCase();
          const provider = route.selected_provider || this.getAiUiPluginProvider(plugin, backend);
          return `${backend} · ${provider} · ${route.selected_model}`;
        }

        return `auto · AutoRotate · ${fallbackModel}`;
      },

      async fetchCodexAuthStatus(pluginId) {
        const id = pluginId || this.aiUI.configModalPluginId;
        if (!id) return;
        try {
          const res = await fetch(`/api/ai-ui/plugins/${id}/codex/auth/status`);
          if (!res.ok) return;
          this.aiUI.codexAuthStatus = await res.json();
        } catch (_e) {
          // Ignore transient status errors
        }
      },

      async startCodexOAuth() {
        const pluginId = this.aiUI.configModalPluginId;
        if (!pluginId) return;
        this.aiUI.codexAuthStatus = { ok: false, logged_in: false, message: "Starting OAuth..." };
        try {
          const res = await fetch(`/api/ai-ui/plugins/${pluginId}/codex/auth/start`, {
            method: "POST",
          });
          const data = await res.json();
          if (!res.ok || data.ok === false) {
            this.aiUI.codexAuthStatus = {
              ok: false,
              logged_in: false,
              message: data.detail || data.message || "Failed to start OAuth",
            };
            this.showToast("Failed to start Codex OAuth", "error");
            return;
          }
          this.aiUI.codexOauthSessionId = data.session_id || null;
          this.aiUI.codexVerificationUri = data.verification_uri || "";
          this.aiUI.codexUserCode = data.user_code || "";
          this.aiUI.codexAuthStatus = {
            ok: false,
            logged_in: false,
            message: data.message || "OAuth started",
          };
          this.showToast("Codex OAuth started", "success");

          if (this.aiUI.codexOauthSessionId) {
            this.aiUI.codexAuthPolling = true;
            await this.pollCodexOAuth(this.aiUI.codexOauthSessionId);
          }
        } catch (e) {
          console.error("Codex OAuth start error:", e);
          this.aiUI.codexAuthStatus = { ok: false, logged_in: false, message: "Request failed" };
          this.showToast("Failed to start Codex OAuth", "error");
        }
      },

      async pollCodexOAuth(sessionId) {
        const pluginId = this.aiUI.configModalPluginId;
        if (!pluginId || !sessionId) return;
        while (
          this.aiUI.codexAuthPolling &&
          this.aiUI.configModalOpen &&
          this.aiUI.codexOauthSessionId === sessionId
        ) {
          try {
            const qs = new URLSearchParams({ session_id: sessionId }).toString();
            const res = await fetch(`/api/ai-ui/plugins/${pluginId}/codex/auth/poll?${qs}`);
            const data = await res.json();
            if (!res.ok || data.status === "error" || data.status === "not_found") {
              this.aiUI.codexAuthStatus = {
                ok: false,
                logged_in: false,
                message: data.detail || data.message || "Codex OAuth failed",
              };
              this.aiUI.codexAuthPolling = false;
              this.showToast("Codex OAuth failed", "error");
              return;
            }
            if (data.verification_uri) this.aiUI.codexVerificationUri = data.verification_uri;
            if (data.user_code) this.aiUI.codexUserCode = data.user_code;
            if (data.status === "completed") {
              this.aiUI.codexAuthPolling = false;
              await this.fetchCodexAuthStatus(pluginId);
              if (this.aiUI.codexAuthStatus?.logged_in) {
                this.showToast("Codex OAuth connected", "success");
              }
              return;
            }
          } catch (_e) {
            // Ignore and retry.
          }
          await new Promise((resolve) => setTimeout(resolve, 2000));
        }
      },

      async fetchQwenAuthStatus(pluginId) {
        const id = pluginId || this.aiUI.configModalPluginId;
        if (!id) return;
        try {
          const res = await fetch(`/api/ai-ui/plugins/${id}/qwen/auth/status`);
          if (!res.ok) return;
          this.aiUI.qwenAuthStatus = await res.json();
        } catch (_e) {
          // Ignore transient status errors
        }
      },

      async startQwenOAuth() {
        const pluginId = this.aiUI.configModalPluginId;
        if (!pluginId) return;
        this.aiUI.qwenAuthStatus = { ok: false, logged_in: false, message: "Starting OAuth..." };
        try {
          const res = await fetch(`/api/ai-ui/plugins/${pluginId}/qwen/auth/start`, {
            method: "POST",
          });
          const data = await res.json();
          if (!res.ok || data.ok === false) {
            this.aiUI.qwenAuthStatus = {
              ok: false,
              logged_in: false,
              message: data.detail || data.message || "Failed to start OAuth",
            };
            this.showToast("Failed to start Qwen OAuth", "error");
            return;
          }
          this.aiUI.qwenOauthSessionId = data.session_id || null;
          this.aiUI.qwenVerificationUri = data.verification_uri || "";
          this.aiUI.qwenUserCode = data.user_code || "";
          this.aiUI.qwenAuthStatus = {
            ok: false,
            logged_in: false,
            message: data.message || "OAuth started",
          };
          this.showToast("Qwen OAuth started", "success");

          if (this.aiUI.qwenOauthSessionId) {
            this.aiUI.qwenAuthPolling = true;
            await this.pollQwenOAuth(this.aiUI.qwenOauthSessionId);
          }
        } catch (e) {
          console.error("Qwen OAuth start error:", e);
          this.aiUI.qwenAuthStatus = { ok: false, logged_in: false, message: "Request failed" };
          this.showToast("Failed to start Qwen OAuth", "error");
        }
      },

      async pollQwenOAuth(sessionId) {
        const pluginId = this.aiUI.configModalPluginId;
        if (!pluginId || !sessionId) return;
        while (
          this.aiUI.qwenAuthPolling &&
          this.aiUI.configModalOpen &&
          this.aiUI.qwenOauthSessionId === sessionId
        ) {
          try {
            const qs = new URLSearchParams({ session_id: sessionId }).toString();
            const res = await fetch(`/api/ai-ui/plugins/${pluginId}/qwen/auth/poll?${qs}`);
            const data = await res.json();
            if (!res.ok || data.status === "error" || data.status === "not_found") {
              this.aiUI.qwenAuthStatus = {
                ok: false,
                logged_in: false,
                message: data.detail || data.message || "Qwen OAuth failed",
              };
              this.aiUI.qwenAuthPolling = false;
              this.showToast("Qwen OAuth failed", "error");
              return;
            }
            if (data.verification_uri) this.aiUI.qwenVerificationUri = data.verification_uri;
            if (data.user_code) this.aiUI.qwenUserCode = data.user_code;
            if (data.status === "completed") {
              this.aiUI.qwenAuthPolling = false;
              await this.fetchQwenAuthStatus(pluginId);
              if (this.aiUI.qwenAuthStatus?.logged_in) {
                this.showToast("Qwen OAuth connected", "success");
              }
              return;
            }
          } catch (_e) {
            // Ignore and retry.
          }
          await new Promise((resolve) => setTimeout(resolve, 2000));
        }
      },

      async fetchGeminiAuthStatus(pluginId) {
        const id = pluginId || this.aiUI.configModalPluginId;
        if (!id) return;
        try {
          const res = await fetch(`/api/ai-ui/plugins/${id}/gemini/auth/status`);
          if (!res.ok) return;
          this.aiUI.geminiAuthStatus = await res.json();
        } catch (_e) {
          // Ignore transient status errors
        }
      },

      async startGeminiOAuth() {
        const pluginId = this.aiUI.configModalPluginId;
        if (!pluginId) return;
        this.aiUI.geminiAuthStatus = { ok: false, logged_in: false, message: "Starting OAuth..." };
        try {
          const res = await fetch(`/api/ai-ui/plugins/${pluginId}/gemini/auth/start`, {
            method: "POST",
          });
          const data = await res.json();
          if (!res.ok || data.ok === false) {
            this.aiUI.geminiAuthStatus = {
              ok: false,
              logged_in: false,
              message: data.detail || data.message || "Failed to start OAuth",
            };
            this.showToast("Failed to start Gemini OAuth", "error");
            return;
          }
          this.aiUI.geminiOauthSessionId = data.session_id || null;
          this.aiUI.geminiVerificationUri = data.verification_uri || "";
          this.aiUI.geminiUserCode = data.user_code || "";
          this.aiUI.geminiAuthStatus = {
            ok: false,
            logged_in: false,
            message: data.message || "OAuth started",
          };
          this.showToast("Gemini OAuth started", "success");

          if (this.aiUI.geminiOauthSessionId) {
            this.aiUI.geminiAuthPolling = true;
            await this.pollGeminiOAuth(this.aiUI.geminiOauthSessionId);
          }
        } catch (e) {
          console.error("Gemini OAuth start error:", e);
          this.aiUI.geminiAuthStatus = { ok: false, logged_in: false, message: "Request failed" };
          this.showToast("Failed to start Gemini OAuth", "error");
        }
      },

      async pollGeminiOAuth(sessionId) {
        const pluginId = this.aiUI.configModalPluginId;
        if (!pluginId || !sessionId) return;
        while (
          this.aiUI.geminiAuthPolling &&
          this.aiUI.configModalOpen &&
          this.aiUI.geminiOauthSessionId === sessionId
        ) {
          try {
            const qs = new URLSearchParams({ session_id: sessionId }).toString();
            const res = await fetch(`/api/ai-ui/plugins/${pluginId}/gemini/auth/poll?${qs}`);
            const data = await res.json();
            if (!res.ok || data.status === "error" || data.status === "not_found") {
              this.aiUI.geminiAuthStatus = {
                ok: false,
                logged_in: false,
                message: data.detail || data.message || "Gemini OAuth failed",
              };
              this.aiUI.geminiAuthPolling = false;
              this.showToast("Gemini OAuth failed", "error");
              return;
            }
            if (data.verification_uri) this.aiUI.geminiVerificationUri = data.verification_uri;
            if (data.user_code) this.aiUI.geminiUserCode = data.user_code;
            if (data.status === "completed") {
              this.aiUI.geminiAuthPolling = false;
              await this.fetchGeminiAuthStatus(pluginId);
              if (this.aiUI.geminiAuthStatus?.logged_in) {
                this.showToast("Gemini OAuth connected", "success");
              }
              return;
            }
          } catch (_e) {
            // Ignore and retry.
          }
          await new Promise((resolve) => setTimeout(resolve, 2000));
        }
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
          this.ensureOllamaConfigDraft(this.aiUI.pluginConfigDraft);
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

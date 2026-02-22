/**
 * PocketPaw - Anti-Detect Browser Module
 *
 * Created: 2026-02-22
 * Full-screen drawer for managing anti-detect browser profiles with
 * actor templates (Web Scraper, Playwright Scraper, Custom Script).
 */

window.PocketPaw = window.PocketPaw || {};

window.PocketPaw.AntiBrowser = {
  name: "AntiBrowser",

  getState() {
    return {
      antiBrowser: {
        drawerOpen: false,
        drawerView: "detail", // 'detail' | 'create'
        loading: false,
        creating: false,
        running: false,
        search: "",
        profiles: [],
        selectedProfile: null,
        actors: [],
        selectedActor: null,
        actorSchema: null,
        actorInputs: {},
        plugins: [],
        lastResult: null,
        _confirmDelete: null,
        form: {
          name: "",
          start_url: "",
          proxy: "",
          os_type: "macos",
          browser_type: "chromium",
          plugin: "playwright",
          notes: "",
        },
      },
    };
  },

  getMethods() {
    return {
      // ==================== Open / Init ====================

      async initAntiBrowser() {
        if (this.antiBrowser.profiles.length === 0) {
          await this.fetchAntiBrowserProfiles();
          await this.fetchAntiBrowserActors();
          await this.fetchAntiBrowserPlugins();
        }
        this.$nextTick(() => {
          if (window.refreshIcons) window.refreshIcons();
        });
      },

      openAntiBrowserDrawer(mode = "detail") {
        this.antiBrowser.drawerOpen = true;
        this.antiBrowser.drawerView = mode;
        if (mode === "create") {
          this.antiBrowser.selectedProfile = null;
        }
        this.$nextTick(() => {
          if (window.refreshIcons) window.refreshIcons();
        });
      },

      // ==================== Profiles ====================

      async fetchAntiBrowserProfiles() {
        this.antiBrowser.loading = true;
        try {
          const res = await fetch("/api/anti-browser/profiles");
          if (res.ok) {
            const data = await res.json();
            this.antiBrowser.profiles = data.profiles || [];
          }
        } catch (e) {
          console.error("Failed to load profiles:", e);
        } finally {
          this.antiBrowser.loading = false;
          this.$nextTick(() => {
            if (window.refreshIcons) window.refreshIcons();
          });
        }
      },

      filteredAntiBrowserProfiles() {
        const q = this.antiBrowser.search.toLowerCase();
        if (!q) return this.antiBrowser.profiles;
        return this.antiBrowser.profiles.filter(
          (p) =>
            p.name.toLowerCase().includes(q) ||
            p.plugin.toLowerCase().includes(q),
        );
      },

      selectAntiBrowserProfile(profile) {
        this.antiBrowser.selectedProfile = profile;
        this.antiBrowser.drawerView = "detail";
        this.antiBrowser.selectedActor = null;
        this.antiBrowser.actorSchema = null;
        this.antiBrowser.actorInputs = {};
        this.antiBrowser.lastResult = null;
        this.antiBrowser.drawerOpen = true;
        this.$nextTick(() => {
          if (window.refreshIcons) window.refreshIcons();
        });
      },

      async createAntiBrowserProfile() {
        const name = this.antiBrowser.form.name.trim();
        if (!name) {
          this.showToast("Profile name is required", "error");
          return;
        }

        this.antiBrowser.creating = true;
        try {
          const res = await fetch("/api/anti-browser/profiles", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(this.antiBrowser.form),
          });
          if (res.ok) {
            const data = await res.json();
            this.antiBrowser.profiles.unshift(data.profile);
            this.antiBrowser.selectedProfile = data.profile;
            this.antiBrowser.drawerView = "detail";
            this.antiBrowser.form = {
              name: "",
              start_url: "",
              proxy: "",
              os_type: "macos",
              browser_type: "chromium",
              plugin: "playwright",
              notes: "",
            };
            this.showToast("Profile created!", "success");
          } else {
            const err = await res.json();
            this.showToast(err.detail || "Failed to create profile", "error");
          }
        } catch (e) {
          console.error("Failed to create profile:", e);
          this.showToast("Failed to create profile", "error");
        } finally {
          this.antiBrowser.creating = false;
          this.$nextTick(() => {
            if (window.refreshIcons) window.refreshIcons();
          });
        }
      },

      async deleteAntiBrowserProfile(profileId) {
        // Two-step confirmation (confirm() is blocked in Electron)
        if (!this.antiBrowser._confirmDelete) {
          this.antiBrowser._confirmDelete = profileId;
          // Auto-reset after 3 seconds if user doesn't confirm
          setTimeout(() => {
            if (this.antiBrowser._confirmDelete === profileId) {
              this.antiBrowser._confirmDelete = null;
            }
          }, 3000);
          return;
        }
        // Second click — actually delete
        this.antiBrowser._confirmDelete = null;
        try {
          const res = await fetch(`/api/anti-browser/profiles/${profileId}`, {
            method: "DELETE",
          });
          if (res.ok) {
            this.antiBrowser.profiles = this.antiBrowser.profiles.filter(
              (p) => p.id !== profileId,
            );
            if (this.antiBrowser.selectedProfile?.id === profileId) {
              this.antiBrowser.selectedProfile = null;
              this.antiBrowser.drawerOpen = false;
            }
            this.showToast("Profile deleted", "info");
          } else {
            const err = await res.json();
            this.showToast(err.detail || "Failed to delete", "error");
          }
        } catch (e) {
          console.error("Failed to delete profile:", e);
          this.showToast("Failed to delete profile", "error");
        }
      },

      async regenerateAntiBrowserFingerprint(profileId) {
        try {
          const res = await fetch(
            `/api/anti-browser/profiles/${profileId}/regenerate-fp`,
            {
              method: "POST",
            },
          );
          if (res.ok) {
            const data = await res.json();
            // Update local profile
            this.antiBrowser.selectedProfile = data.profile;
            const idx = this.antiBrowser.profiles.findIndex(
              (p) => p.id === profileId,
            );
            if (idx >= 0) this.antiBrowser.profiles[idx] = data.profile;
            this.showToast("Fingerprint regenerated", "success");
          } else {
            const err = await res.json();
            this.showToast(err.detail || "Failed to regenerate", "error");
          }
        } catch (e) {
          this.showToast("Failed to regenerate fingerprint", "error");
        }
      },

      async stopAntiBrowserProfile(profileId) {
        try {
          const res = await fetch(
            `/api/anti-browser/profiles/${profileId}/stop`,
            { method: "POST" },
          );
          if (res.ok) {
            const data = await res.json();
            // Update local state
            const idx = this.antiBrowser.profiles.findIndex(
              (p) => p.id === profileId,
            );
            if (idx >= 0) this.antiBrowser.profiles[idx].status = "IDLE";
            if (this.antiBrowser.selectedProfile?.id === profileId) {
              this.antiBrowser.selectedProfile.status = "IDLE";
            }
            this.showToast("Session stopped", "info");
          } else {
            const err = await res.json();
            this.showToast(err.detail || "Failed to stop session", "error");
          }
        } catch (e) {
          console.error("Failed to stop profile session:", e);
          this.showToast("Failed to stop session", "error");
        }
      },

      // ==================== Actors ====================

      async fetchAntiBrowserActors() {
        try {
          const res = await fetch("/api/anti-browser/actors");
          if (res.ok) {
            const data = await res.json();
            this.antiBrowser.actors = data.actors || [];
          }
        } catch (e) {
          console.error("Failed to load actors:", e);
        }
        this.$nextTick(() => {
          if (window.refreshIcons) window.refreshIcons();
        });
      },

      async selectAntiBrowserActor(actorId) {
        // Toggle: collapse if clicking the already-selected actor
        if (this.antiBrowser.selectedActor === actorId) {
          this.antiBrowser.selectedActor = null;
          this.antiBrowser.actorSchema = null;
          this.antiBrowser.actorInputs = {};
          this.$nextTick(() => {
            if (window.refreshIcons) window.refreshIcons();
          });
          return;
        }

        this.antiBrowser.selectedActor = actorId;
        this.antiBrowser.actorInputs = {};

        try {
          const res = await fetch(`/api/anti-browser/actors/${actorId}/schema`);
          if (res.ok) {
            const data = await res.json();
            this.antiBrowser.actorSchema = data.input_schema;

            // Pre-fill defaults
            const props = data.input_schema?.properties || {};
            for (const [key, prop] of Object.entries(props)) {
              if (prop.default !== undefined) {
                this.antiBrowser.actorInputs[key] = prop.default;
              }
            }

            // Pre-fill start_urls from profile
            if (
              this.antiBrowser.selectedProfile?.start_url &&
              props.start_urls
            ) {
              this.antiBrowser.actorInputs.start_urls =
                this.antiBrowser.selectedProfile.start_url;
            }
          }
        } catch (e) {
          console.error("Failed to load actor schema:", e);
        }
        this.$nextTick(() => {
          if (window.refreshIcons) window.refreshIcons();
        });
      },

      // ==================== Run ====================

      async runAntiBrowserActor() {
        if (
          !this.antiBrowser.selectedProfile ||
          !this.antiBrowser.selectedActor
        ) {
          this.showToast("Select a profile and actor template first", "error");
          return;
        }

        this.antiBrowser.running = true;
        this.antiBrowser.lastResult = null;
        const profileId = this.antiBrowser.selectedProfile.id;

        // Update status locally
        this.antiBrowser.selectedProfile.status = "RUNNING";
        const idx = this.antiBrowser.profiles.findIndex(
          (p) => p.id === profileId,
        );
        if (idx >= 0) this.antiBrowser.profiles[idx].status = "RUNNING";

        try {
          const res = await fetch(
            `/api/anti-browser/profiles/${profileId}/run`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                actor_id: this.antiBrowser.selectedActor,
                inputs: this.antiBrowser.actorInputs,
              }),
            },
          );

          if (res.ok) {
            const data = await res.json();
            this.antiBrowser.lastResult = data.result;
            this.antiBrowser.selectedProfile = data.profile;
            if (idx >= 0) this.antiBrowser.profiles[idx] = data.profile;
            this.showToast(
              `Done! ${data.result.items_extracted} items extracted`,
              "success",
            );
          } else {
            const err = await res.json();
            this.showToast(err.detail || "Actor run failed", "error");
            // Reset status
            if (idx >= 0) this.antiBrowser.profiles[idx].status = "ERROR";
            this.antiBrowser.selectedProfile.status = "ERROR";
          }
        } catch (e) {
          console.error("Actor run error:", e);
          this.showToast("Actor run failed", "error");
          this.antiBrowser.selectedProfile.status = "ERROR";
        } finally {
          this.antiBrowser.running = false;
          this.$nextTick(() => {
            if (window.refreshIcons) window.refreshIcons();
          });
        }
      },

      // ==================== Plugins ====================

      async fetchAntiBrowserPlugins() {
        try {
          const res = await fetch("/api/anti-browser/plugins");
          if (res.ok) {
            const data = await res.json();
            this.antiBrowser.plugins = (data.plugins || []).map((p) => ({
              ...p,
              installing: false,
            }));
          }
        } catch (e) {
          console.error("Failed to load plugins:", e);
        }
      },

      async installAntiBrowserPlugin(pluginId) {
        const plugin = this.antiBrowser.plugins.find((p) => p.id === pluginId);
        if (!plugin) return;

        plugin.installing = true;
        try {
          const res = await fetch(
            `/api/anti-browser/plugins/${pluginId}/install`,
            {
              method: "POST",
            },
          );
          if (res.ok) {
            this.showToast(`${plugin.name} installed successfully`, "success");
            await this.fetchAntiBrowserPlugins();
          } else {
            const err = await res.json();
            this.showToast(err.detail || "Installation failed", "error");
          }
        } catch (e) {
          console.error("Install error:", e);
          this.showToast("Installation failed. Check server logs.", "error");
        } finally {
          plugin.installing = false;
        }
      },
    };
  },
};

window.PocketPaw.Loader.register("AntiBrowser", window.PocketPaw.AntiBrowser);

/**
 * PocketPaw WebSocket Module
 * Singleton WebSocket connection with proper state management
 *
 * Changes:
 *   - 2026-02-06: Auto-upgrade to wss:// on HTTPS; send token via first message instead of URL.
 */

class PocketPawSocket {
    constructor() {
        this.ws = null;
        this.handlers = new Map();
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.isConnecting = false;
        this.isConnected = false;
    }

    /**
     * Connect to WebSocket server (only if not already connected)
     */
    connect() {
        // Prevent multiple connections
        if (this.isConnected || this.isConnecting) {
            console.log('[WS] Already connected or connecting');
            return;
        }
        
        this.isConnecting = true;
        const token = localStorage.getItem('pocketpaw_token');
        // Auto-upgrade to wss:// when page is served over HTTPS
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${window.location.host}/ws`;
        console.log('[WS] Connecting to', url);

        this.ws = new WebSocket(url);

        this.ws.onopen = () => {
            console.log('[WS] Connected');
            this.isConnecting = false;
            this.isConnected = true;
            this.reconnectAttempts = 0;
            // Authenticate via first message (not URL query param)
            if (token) {
                this.ws.send(JSON.stringify({ action: 'authenticate', token }));
            }
            this.emit('connected');
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleMessage(data);
            } catch (e) {
                console.error('[WS] Parse error:', e);
            }
        };

        this.ws.onclose = (event) => {
            console.log(`[WS] Disconnected (Code: ${event.code})`);
            
            // Handle Auth Failure specifically
            if (event.code === 4003) {
                console.error('[WS] Authentication failed');
                this.emit('auth_error');
                // Clear invalid token
                localStorage.removeItem('pocketpaw_token');
                return; // Do not reconnect
            }

            this.isConnecting = false;
            this.isConnected = false;
            this.emit('disconnected');
            this.attemptReconnect();
        };

        this.ws.onerror = (error) => {
            console.error('[WS] Error:', error);
            this.isConnecting = false;
            this.emit('error', error);
        };
    }

    /**
     * Attempt to reconnect with exponential backoff
     */
    attemptReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.log('[WS] Max reconnect attempts reached');
            this.emit('maxReconnectReached');
            return;
        }

        const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 10000);
        this.reconnectAttempts++;

        console.log(`[WS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
        setTimeout(() => this.connect(), delay);
    }

    /**
     * Handle incoming messages - route to type-specific handlers
     */
    handleMessage(data) {
        const type = data.type;

        // Emit to type-specific handlers first
        if (type && this.handlers.has(type)) {
            this.handlers.get(type).forEach(handler => handler(data));
        }
    }

    /**
     * Register event handler
     */
    on(event, handler) {
        if (!this.handlers.has(event)) {
            this.handlers.set(event, []);
        }
        this.handlers.get(event).push(handler);
    }

    /**
     * Remove event handler
     */
    off(event, handler) {
        if (this.handlers.has(event)) {
            const handlers = this.handlers.get(event);
            const index = handlers.indexOf(handler);
            if (index > -1) {
                handlers.splice(index, 1);
            }
        }
    }

    /**
     * Clear all handlers for an event or all events
     */
    clearHandlers(event = null) {
        if (event) {
            this.handlers.delete(event);
        } else {
            this.handlers.clear();
        }
    }

    /**
     * Emit event to handlers
     */
    emit(event, data = null) {
        if (this.handlers.has(event)) {
            this.handlers.get(event).forEach(handler => handler(data));
        }
    }

    /**
     * Send message to server
     */
    send(action, data = {}) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ action, ...data }));
            return true;
        } else {
            console.warn('[WS] Not connected, cannot send:', action);
            return false;
        }
    }

    /**
     * Convenience methods for common actions
     */
    runTool(tool, options = {}) {
        this.send('tool', { tool, ...options });
    }

    toggleAgent(active) {
        this.send('toggle_agent', { active });
    }

    chat(message) {
        this.send('chat', { message });
    }

    saveSettings(agentBackend, llmProvider, anthropicModel, bypassPermissions) {
        this.send('settings', {
            agent_backend: agentBackend,
            llm_provider: llmProvider,
            anthropic_model: anthropicModel,
            bypass_permissions: bypassPermissions
        });
    }

    saveApiKey(provider, key) {
        this.send('save_api_key', { provider, key });
    }
}

// Export singleton - only one instance ever
window.socket = window.socket || new PocketPawSocket();

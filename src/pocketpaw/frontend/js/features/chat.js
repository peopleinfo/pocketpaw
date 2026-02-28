/**
 * PocketPaw - Chat Feature Module
 *
 * Created: 2026-02-05
 * Extracted from app.js as part of componentization refactor.
 *
 * Contains chat/messaging functionality:
 * - Message handling
 * - Streaming support
 * - Chat scroll management
 */

window.PocketPaw = window.PocketPaw || {};

window.PocketPaw.Chat = {
    name: 'Chat',
    /**
     * Get initial state for Chat
     */
    getState() {
        return {
            // Agent state
            agentActive: true,
            isStreaming: false,
            isThinking: false,
            isStopRequested: false,
            streamingContent: '',
            streamingMessageId: null,
            hasShownWelcome: false,
            showComposerHelp: false,
            quickCommands: [
                { command: '/help', description: 'Show all chat commands and usage tips.' },
                { command: '/tools', description: 'List the tools currently enabled.' },
                { command: '/backends', description: 'Show available agent backends.' },
                { command: '/status', description: 'Check current system status.' },
                {
                    command: 'What can you do in this project?',
                    description: 'Ask the agent for concrete capabilities here.'
                }
            ],

            // Messages
            messages: [],
            inputText: ''
        };
    },

    /**
     * Get methods for Chat
     */
    getMethods() {
        return {
            /**
             * Handle notification
             */
            handleNotification(data) {
                const content = data.content || '';

                // Skip duplicate connection messages
                if (content.includes('Connected to PocketPaw') && this.hasShownWelcome) {
                    return;
                }
                if (content.includes('Connected to PocketPaw')) {
                    this.hasShownWelcome = true;
                }

                this.showToast(content, 'info');
                this.log(content, 'info');
            },

            /**
             * Handle incoming message
             */
            handleMessage(data) {
                const content = data.content || '';

                // Check if it's a status update (don't show in chat)
                if (content.includes('System Status') || content.includes('🧠 CPU:')) {
                    this.status = Tools.parseStatus(content);
                    return;
                }

                // Server-side stream flag — auto-enter streaming if we missed stream_start
                if (data.is_stream_chunk && !this.isStreaming) {
                    this.startStreaming();
                }

                // Clear thinking state on first text content
                if (this.isThinking && content) {
                    this.isThinking = false;
                }

                // Handle streaming vs complete messages
                if (this.isStreaming) {
                    this.streamingContent += content;
                    // Scroll during streaming to follow new content
                    this.$nextTick(() => this.scrollToBottom());
                    // Don't log streaming chunks - they flood the terminal
                } else {
                    this.addMessage('assistant', content);
                    // Only log complete messages (not streaming chunks)
                    if (content.trim()) {
                        this.log(content.substring(0, 100) + (content.length > 100 ? '...' : ''), 'info');
                    }
                }
            },

            /**
             * Handle code blocks
             */
            handleCode(data) {
                const content = data.content || '';
                if (this.isStreaming) {
                    this.streamingContent += '\n```\n' + content + '\n```\n';
                } else {
                    this.addMessage('assistant', '```\n' + content + '\n```');
                }
            },

            /**
             * Start streaming mode
             */
            startStreaming() {
                this.isStreaming = true;
                this.isThinking = true;
                this.isStopRequested = false;
                this.streamingContent = '';
            },

            /**
             * End streaming mode
             */
            endStreaming() {
                if (this.isStreaming && this.streamingContent) {
                    this.addMessage('assistant', this.streamingContent);
                }
                this.isStreaming = false;
                this.isThinking = false;
                this.isStopRequested = false;
                this.streamingContent = '';

                // Refresh sidebar sessions and auto-title
                if (this.loadSessions) this.loadSessions();
                if (this.autoTitleCurrentSession) this.autoTitleCurrentSession();
            },

            /**
             * Add a message to the chat
             */
            addMessage(role, content) {
                this.messages.push({
                    role,
                    content: content || '',
                    time: Tools.formatTime(),
                    isNew: true
                });

                // Auto scroll to bottom with slight delay for DOM update
                this.$nextTick(() => {
                    this.scrollToBottom();
                });
            },

            /**
             * Scroll chat to bottom
             */
            scrollToBottom() {
                if (this._scrollRAF) return;
                this._scrollRAF = requestAnimationFrame(() => {
                    const el = this.$refs.messages;
                    if (el) el.scrollTop = el.scrollHeight;
                    this._scrollRAF = null;
                });
            },

            /**
             * Send a chat message
             */
            sendMessage() {
                const text = this.inputText.trim();
                if (!text) return;

                // Check for skill command (starts with /)
                // Only intercept if the name matches a registered skill;
                // otherwise fall through to chat so CommandHandler picks it up
                // (e.g. /backend, /backends, /model, /tools, /help, etc.)
                if (text.startsWith('/')) {
                    const slash = this.parseSlashCommand(text);
                    const skill = slash ? this.findSkillByName(slash.command) : null;

                    if (skill && slash) {
                        const args = slash.args.trim();
                        if (this.skillHasRequiredArgs(skill) && !args) {
                            const usage = this.getSkillUsageText(skill);
                            this.showToast(`Usage: ${usage}`, 'error');
                            this.log(`Skill requires arguments: ${usage}`, 'warning');
                            return;
                        }

                        this.addMessage('user', text);
                        this.inputText = '';
                        this.startStreaming();
                        socket.send('run_skill', { name: skill.name, args });
                        this.log(`Running skill: /${skill.name} ${args}`, 'info');
                        return;
                    }
                    // Not a skill — fall through to send as normal message
                }

                // Add user message
                this.addMessage('user', text);
                this.inputText = '';
                this.showComposerHelp = false;

                // Start streaming indicator
                this.startStreaming();

                // Send to server
                socket.chat(text);

                this.log(`You: ${text}`, 'info');
            },

            /**
             * Toggle agent mode
             */
            /**
             * Stop in-flight response
             */
            stopResponse() {
                if (!this.isStreaming) return;
                this.isStopRequested = true;
                socket.stopResponse();
                this.log('Stop requested', 'info');
            },

            toggleAgent() {
                socket.toggleAgent(this.agentActive);
                this.log(`Switched Agent Mode: ${this.agentActive ? 'ON' : 'OFF'}`, 'info');
            },

            /**
             * Toggle quick command/help panel above chat composer.
             */
            toggleComposerHelp() {
                this.showComposerHelp = !this.showComposerHelp;
                if (this.showComposerHelp) {
                    this.$nextTick(() => {
                        if (this.$refs.chatInput) this.$refs.chatInput.focus();
                    });
                }
            },

            /**
             * Keyboard support for chat composer helpers.
             */
            handleComposerKeydown(event) {
                const slashShortcut = (event.metaKey || event.ctrlKey) && event.key === '/';
                if (slashShortcut) {
                    event.preventDefault();
                    this.toggleComposerHelp();
                    return;
                }

                if (event.key === 'Escape' && this.showComposerHelp) {
                    event.preventDefault();
                    this.showComposerHelp = false;
                }
            },

            /**
             * Parse slash command text into command and args.
             */
            parseSlashCommand(text) {
                const raw = (text || '').trimStart();
                if (!raw.startsWith('/')) return null;

                const commandText = raw.slice(1);
                if (!commandText) return null;

                const firstSpace = commandText.indexOf(' ');
                if (firstSpace === -1) {
                    return { command: commandText, args: '' };
                }

                return {
                    command: commandText.slice(0, firstSpace),
                    args: commandText.slice(firstSpace + 1)
                };
            },

            /**
             * Find a skill by name (case-insensitive).
             */
            findSkillByName(name) {
                if (!name) return null;
                return (this.skills || []).find(
                    (s) => s.name.toLowerCase() === name.toLowerCase()
                ) || null;
            },

            /**
             * True when a skill hint declares at least one required arg (`<...>`).
             */
            skillHasRequiredArgs(skill) {
                return Boolean(skill?.argument_hint && /<[^>]+>/.test(skill.argument_hint));
            },

            /**
             * Render usage text shown in composer and validation.
             */
            getSkillUsageText(skill) {
                if (!skill) return '';
                return skill.argument_hint
                    ? `/${skill.name} ${skill.argument_hint}`
                    : `/${skill.name}`;
            },

            /**
             * Build a lightweight example command from argument-hint placeholders.
             */
            getSkillExampleText(skill) {
                if (!skill || !skill.argument_hint) return '';

                const sampleForToken = (token) => {
                    const clean = token.replace(/[<>\[\]]/g, '').toLowerCase();
                    if (clean.includes('url') || clean.includes('repo')) return 'owner/repo';
                    if (clean.includes('path')) return './my-app';
                    if (clean.includes('id') || clean.includes('name')) return 'my-plugin';
                    return clean.replace(/[^a-z0-9_-]+/g, '-') || 'value';
                };

                const args = skill.argument_hint
                    .split(/\s+/)
                    .map((token) => {
                        if (token.startsWith('<') && token.endsWith('>')) return sampleForToken(token);
                        if (token.startsWith('[') && token.endsWith(']')) return '';
                        return '';
                    })
                    .filter(Boolean)
                    .join(' ');

                return args ? `/${skill.name} ${args}` : `/${skill.name}`;
            },

            /**
             * Resolve current slash-skill context from the input box.
             */
            getActiveSkillContext() {
                const slash = this.parseSlashCommand(this.inputText);
                if (!slash) return null;
                const skill = this.findSkillByName(slash.command);
                if (!skill) return null;

                return {
                    skill,
                    args: slash.args || '',
                    hasArgs: Boolean((slash.args || '').trim()),
                    usage: this.getSkillUsageText(skill),
                    example: this.getSkillExampleText(skill),
                    requiresArgs: this.skillHasRequiredArgs(skill)
                };
            },

            /**
             * Filter quick commands when user starts typing "/" commands.
             */
            getVisibleQuickCommands() {
                const query = (this.inputText || '').trim().toLowerCase();
                if (!query.startsWith('/')) return this.quickCommands;
                return this.quickCommands.filter((item) =>
                    item.command.toLowerCase().includes(query)
                    || item.description.toLowerCase().includes(query)
                );
            },

            /**
             * Put a quick command/prompt into the chat input.
             */
            insertQuickCommand(command) {
                const needsSpace = command.startsWith('/');
                this.inputText = needsSpace ? `${command} ` : command;
                this.showComposerHelp = false;
                this.$nextTick(() => {
                    if (this.$refs.chatInput) this.$refs.chatInput.focus();
                });
            },

            /**
             * Helpers for composer hint bindings.
             */
            shouldShowSkillHint() {
                return Boolean(this.getActiveSkillContext());
            },

            getActiveSkillUsage() {
                const ctx = this.getActiveSkillContext();
                return ctx ? ctx.usage : '';
            },

            getActiveSkillExample() {
                const ctx = this.getActiveSkillContext();
                return ctx ? ctx.example : '';
            },

            activeSkillNeedsArgs() {
                const ctx = this.getActiveSkillContext();
                return Boolean(ctx && ctx.requiresArgs);
            },

            activeSkillHasArgs() {
                const ctx = this.getActiveSkillContext();
                return Boolean(ctx && ctx.hasArgs);
            },

            /**
             * Determine whether submit should be enabled.
             */
            canSubmitInput() {
                const text = (this.inputText || '').trim();
                if (!text) return false;

                const ctx = this.getActiveSkillContext();
                if (!ctx) return true;

                if (!ctx.requiresArgs) return true;
                return ctx.hasArgs;
            }
        };
    }
};

window.PocketPaw.Loader.register('Chat', window.PocketPaw.Chat);

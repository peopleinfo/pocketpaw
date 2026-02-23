# 🐾 PocketPaw — Roadmap

> **Last updated:** 2026-02-24

This document tracks every shipped feature and planned work for PocketPaw.
Items marked ✅ are **done and available today**. Items marked 🚧 are **in progress**, and 📋 are **planned**.

---

## Table of Contents

- [Channels](#channels)
- [Agent Backends](#agent-backends)
- [Built-in Tools](#built-in-tools)
- [Integrations](#integrations)
- [Memory System](#memory-system)
- [Security](#security)
- [Dashboard & UI](#dashboard--ui)
- [Deep Work / Mission Control](#deep-work--mission-control)
- [Anti-Detect Browser](#anti-detect-browser)
- [MCP (Model Context Protocol)](#mcp-model-context-protocol)
- [Daemon & Proactive Agent](#daemon--proactive-agent)
- [Infrastructure](#infrastructure)
- [Developer Experience](#developer-experience)

---

## Channels

| Status | Feature         | Description                             |
| ------ | --------------- | --------------------------------------- |
| ✅     | Web Dashboard   | Built-in browser UI at `localhost:8888` |
| ✅     | Discord         | Full Discord bot gateway                |
| ✅     | Slack           | Slack bot gateway                       |
| ✅     | WhatsApp        | WhatsApp messaging gateway              |
| ✅     | Telegram        | Telegram bot support                    |
| ✅     | Signal          | Signal messenger channel                |
| ✅     | Matrix          | Matrix protocol channel                 |
| ✅     | Microsoft Teams | Teams channel                           |
| ✅     | Google Chat     | Google Chat channel                     |

---

## Agent Backends

| Status | Feature                    | Key                | Providers                                        | MCP Support |
| ------ | -------------------------- | ------------------ | ------------------------------------------------ | :---------: |
| ✅     | Claude Agent SDK (Default) | `claude_agent_sdk` | Anthropic, Ollama                                |     Yes     |
| ✅     | OpenAI Agents SDK          | `openai_agents`    | OpenAI, Ollama                                   |     No      |
| ✅     | Google ADK                 | `google_adk`       | Google (Gemini)                                  |     Yes     |
| ✅     | Codex CLI                  | `codex_cli`        | OpenAI                                           |     Yes     |
| ✅     | OpenCode                   | `opencode`         | External server                                  |     No      |
| ✅     | Copilot SDK                | `copilot_sdk`      | Copilot, OpenAI, Azure, Anthropic                |     No      |
| ✅     | Agent Delegation           | —                  | Spawn sub-agents for parallel work               |      —      |
| ✅     | Model Router               | —                  | Automatic model selection across providers       |      —      |
| ✅     | Plan Mode                  | —                  | Human-in-the-loop approval before tool execution |      —      |

---

## Built-in Tools

| Status | Tool                 | Description                                    |
| ------ | -------------------- | ---------------------------------------------- |
| ✅     | Browser Automation   | Web browsing, page interaction, screenshots    |
| ✅     | Web Search           | Internet search via multiple providers         |
| ✅     | URL Extraction       | Fetch and parse web page content               |
| ✅     | Shell / CLI          | Execute shell commands                         |
| ✅     | File System          | Read, write, list files and directories        |
| ✅     | Image Generation     | AI image generation                            |
| ✅     | OCR                  | Optical character recognition from images      |
| ✅     | Voice / TTS          | Text-to-speech synthesis                       |
| ✅     | Speech-to-Text (STT) | Audio transcription                            |
| ✅     | Translation          | Multi-language text translation                |
| ✅     | Research             | Multi-step deep research with citations        |
| ✅     | Delegation           | Delegate tasks to sub-agents                   |
| ✅     | Skill Generation     | Create reusable skills from conversations      |
| ✅     | Memory Tools         | Store, recall, and search long-term memory     |
| ✅     | Session Management   | Manage conversation sessions                   |
| ✅     | Health Check         | System diagnostics and health monitoring       |
| ✅     | Desktop Automation   | Desktop control and interaction                |
| ✅     | Screenshot           | Capture screen and window screenshots          |
| ✅     | Anti-Detect Browser  | Manage anti-detect browser profiles and actors |

---

## Integrations

| Status | Integration       | Description                                    |
| ------ | ----------------- | ---------------------------------------------- |
| ✅     | Gmail             | Read, send, search emails; manage labels       |
| ✅     | Google Calendar   | Create, list, update calendar events           |
| ✅     | Google Drive      | Upload, download, search files in Drive        |
| ✅     | Google Docs       | Create and edit Google Docs                    |
| ✅     | Spotify           | Playback control, search, playlist management  |
| ✅     | Reddit            | Browse, search, post on Reddit                 |
| ✅     | OAuth Token Store | Secure OAuth token management for integrations |
| ✅     | MCP Servers       | Connect to any Model Context Protocol server   |

---

## Memory System

| Status | Feature                | Description                                            |
| ------ | ---------------------- | ------------------------------------------------------ |
| ✅     | Long-term Fact Storage | Persistent fact extraction and retrieval               |
| ✅     | Session History        | Conversation history within sessions                   |
| ✅     | Smart Compaction       | Automatic context compaction for long conversations    |
| ✅     | File-based Store       | Local JSON file memory backend                         |
| ✅     | Mem0 Semantic Search   | Vector-based semantic memory search (Mem0 integration) |

---

## Security

| Status | Feature               | Description                                              |
| ------ | --------------------- | -------------------------------------------------------- |
| ✅     | Guardian AI           | Secondary LLM reviews every tool call before execution   |
| ✅     | Injection Scanner     | Detects prompt injection attacks in messages             |
| ✅     | Tool Policy Engine    | Configurable allow/deny rules for tool execution         |
| ✅     | Rate Limiter          | Rate limiting for API and tool usage                     |
| ✅     | Audit Log             | Append-only audit log for all actions                    |
| ✅     | Security Audit CLI    | `--security-audit` CLI command for security review       |
| ✅     | Safety Rails          | Configurable safety boundaries for agent behavior        |
| ✅     | PII Redaction         | Automatically redact sensitive data from logs            |
| ✅     | Session Tokens        | Secure session token management                          |
| ✅     | Self-Audit Daemon     | Background daemon that continuously audits agent actions |
| ✅     | Dashboard Auth        | Token-based authentication for the web dashboard         |
| ✅     | Encrypted Credentials | API keys encrypted at rest                               |

---

## Dashboard & UI

| Status | Feature                | Description                                   |
| ------ | ---------------------- | --------------------------------------------- |
| ✅     | Chat View              | Real-time chat interface with the agent       |
| ✅     | Activity Feed          | Live activity and event stream                |
| ✅     | Terminal               | Built-in web terminal                         |
| ✅     | Deep Work View         | Focused deep work / mission control interface |
| ✅     | Anti-Browser View      | Anti-detect browser profile management UI     |
| ✅     | Sidebar Navigation     | Sidebar with tools & config sections          |
| ✅     | Channel Management     | Connect/disconnect messaging channels from UI |
| ✅     | Settings Panel         | Configure agent settings from the dashboard   |
| ✅     | Health Monitor         | System health and diagnostics dashboard       |
| ✅     | Session Manager        | View and manage conversation sessions         |
| ✅     | MCP Server Manager     | Add, remove, and configure MCP servers        |
| ✅     | Skills Manager         | View and manage agent skills                  |
| ✅     | File Browser           | Browse workspace files                        |
| ✅     | Project Browser        | Navigate project structure                    |
| ✅     | Remote Access / Tunnel | Expose dashboard via secure tunnel            |
| ✅     | Reminders              | Schedule and manage reminders                 |
| ✅     | Transparency View      | Inspect agent reasoning and tool calls        |
| ✅     | Plan Mode UI           | Approve/reject tool calls in plan mode        |
| ✅     | Intentions             | View and manage agent intentions              |
| ✅     | WebSocket Real-time    | Live updates via WebSocket connection         |
| ✅     | Hash Router            | Client-side routing for SPA-like navigation   |
| ✅     | Modal System           | Reusable modal dialogs across the dashboard   |

---

## Deep Work / Mission Control

| Status | Feature           | Description                                        |
| ------ | ----------------- | -------------------------------------------------- |
| ✅     | Goal Parser       | Parse natural language goals into structured plans |
| ✅     | Task Planner      | Break goals into executable task sequences         |
| ✅     | Task Executor     | Autonomous task execution engine                   |
| ✅     | Mission Store     | Persistent mission and task storage                |
| ✅     | Human Tasks       | Tasks that require human input or approval         |
| ✅     | Mission Sessions  | Isolated sessions per mission                      |
| ✅     | Mission Scheduler | Schedule missions for later execution              |
| ✅     | Mission API       | REST API for mission management                    |
| ✅     | Agent System      | Multi-agent coordination for missions              |
| ✅     | Event System      | Mission lifecycle events and notifications         |
| ✅     | Heartbeat         | Mission health monitoring via heartbeats           |

---

## Anti-Detect Browser

| Status | Feature              | Description                                    |
| ------ | -------------------- | ---------------------------------------------- |
| ✅     | Browser Profiles     | Create and manage anti-detect browser profiles |
| ✅     | Actor Management     | Manage browser actors (personas)               |
| ✅     | Fingerprint Spoofing | Browser fingerprint generation and spoofing    |
| ✅     | Plugin System        | Installable browser plugins (e.g., Camoufox)   |
| ✅     | Browser Driver       | Automated browser session management           |
| ✅     | Session Snapshots    | Save and restore browser session state         |

---

## MCP (Model Context Protocol)

| Status | Feature            | Description                                    |
| ------ | ------------------ | ---------------------------------------------- |
| ✅     | MCP Client         | Connect to external MCP servers                |
| ✅     | MCP Server Manager | Add/remove/configure MCP servers via dashboard |
| ✅     | MCP Presets        | Pre-configured MCP server presets              |
| ✅     | MCP OAuth Store    | OAuth token management for MCP servers         |
| ✅     | MCP Config         | YAML/JSON-based MCP server configuration       |

---

## Daemon & Proactive Agent

| Status | Feature             | Description                                       |
| ------ | ------------------- | ------------------------------------------------- |
| ✅     | Background Daemon   | Agent runs as a background service                |
| ✅     | Proactive Agent     | Agent can initiate actions without user prompting |
| ✅     | Context Awareness   | Daemon maintains contextual awareness             |
| ✅     | Trigger System      | Event-based triggers for proactive actions        |
| ✅     | Intention Detection | Detect user intentions from context               |
| ✅     | Self-Audit          | Continuous self-auditing of agent behavior        |
| ✅     | Scheduler           | Time-based task scheduling (cron-like)            |

---

## Infrastructure

| Status | Feature              | Description                                 |
| ------ | -------------------- | ------------------------------------------- |
| ✅     | Event-Driven Bus     | Central message bus architecture            |
| ✅     | Docker Support       | `docker compose` deployment                 |
| ✅     | Windows Installer    | One-click `.exe` installer for Windows      |
| ✅     | Electron App         | Desktop application via Electron            |
| ✅     | PyPI Package         | Installable via `pip install pocketpaw`     |
| ✅     | Install Scripts      | `curl` / PowerShell install scripts         |
| ✅     | Ollama Support       | Fully offline LLM operation via Ollama      |
| ✅     | Headless Mode        | Run without dashboard UI                    |
| ✅     | Update Checker       | Automatic update notifications              |
| ✅     | Logging System       | Structured logging with configurable levels |
| ✅     | Health Checks        | `/health` endpoint and diagnostics          |
| ✅     | Lifecycle Management | Graceful startup, shutdown, and restart     |
| ✅     | Secure Tunnel        | Expose local instance via public URL        |

---

## Developer Experience

| Status | Feature            | Description                                     |
| ------ | ------------------ | ----------------------------------------------- |
| ✅     | Dev Mode           | `--dev` flag with auto-reload                   |
| ✅     | 2000+ Tests        | Comprehensive test suite                        |
| ✅     | Ruff Linting       | Code linting and formatting                     |
| ✅     | `uv` Support       | Fast dependency management with `uv`            |
| ✅     | Optional Extras    | Modular `pip install pocketpaw[extra]` packages |
| ✅     | Skills System      | Create and share reusable agent skills          |
| ✅     | Tool Protocol      | Extensible tool registration protocol           |
| ✅     | Tool Registry      | Dynamic tool discovery and registration         |
| ✅     | Agent Protocol     | Pluggable agent backend protocol                |
| ✅     | Agent Registry     | Dynamic agent backend registration              |
| ✅     | Contributing Guide | `CONTRIBUTING.md` with development guidelines   |

---

## Planned / Future

> Add upcoming features here as they are planned.

| Status | Feature             | Description   |
| ------ | ------------------- | ------------- |
| 📋     | _Your next feature_ | _Description_ |

---

<p align="center">
  <img src="paw.png" alt="PocketPaw" width="40">
  <br>
  <strong>Built for people who'd rather own their AI than rent it</strong>
</p>

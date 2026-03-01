"""Codex CLI backend for PocketPaw.

Spawns OpenAI's Codex CLI (npm install -g @openai/codex) as a subprocess
and parses its streaming NDJSON output. Analogous to Gemini CLI but for Codex.

Built-in tools: shell (command_execution), file editing (file_change),
MCP tool calls, web search.

Requires: OPENAI_API_KEY (or CODEX_API_KEY) env var and `codex` on PATH.

Windows notes:
  - npm global installs create .cmd batch wrappers — commands are wrapped
    with ``cmd.exe /c`` automatically.
  - uvicorn reload mode uses SelectorEventLoop which does NOT support
    ``asyncio.create_subprocess_exec``. A ``subprocess.Popen`` fallback
    is used automatically in that case.
"""

import asyncio
import json
import logging
import shutil
import subprocess
import sys
from collections.abc import AsyncIterator
from typing import Any

from pocketpaw.agents.backend import BackendInfo, Capability
from pocketpaw.agents.protocol import AgentEvent
from pocketpaw.config import Settings

logger = logging.getLogger(__name__)


class CodexCLIBackend:
    """Codex CLI backend — subprocess wrapper for OpenAI's terminal AI agent."""

    @staticmethod
    def info() -> BackendInfo:
        return BackendInfo(
            name="codex_cli",
            display_name="Codex CLI",
            capabilities=(
                Capability.STREAMING
                | Capability.TOOLS
                | Capability.MCP
                | Capability.MULTI_TURN
                | Capability.CUSTOM_SYSTEM_PROMPT
            ),
            builtin_tools=["shell", "file_edit", "web_search", "mcp"],
            tool_policy_map={
                "shell": "shell",
                "file_edit": "write_file",
                "web_search": "browser",
                "mcp": "mcp",
            },
            required_keys=["openai_api_key"],
            supported_providers=["openai"],
            install_hint={
                "external_cmd": "npm install -g @openai/codex",
            },
            beta=True,
        )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._stop_flag = False
        self._cli_available = shutil.which("codex") is not None
        self._process: asyncio.subprocess.Process | None = None
        self._sync_process: subprocess.Popen | None = None
        if self._cli_available:
            logger.info("Codex CLI found on PATH")
        else:
            logger.warning("Codex CLI not found — install with: npm install -g @openai/codex")

    @staticmethod
    def _resolve_cmd(cmd: list[str]) -> list[str]:
        """Wrap command for Windows .cmd/.bat shim compatibility.

        On Windows, npm global installs create ``.cmd`` batch wrappers.
        ``asyncio.create_subprocess_exec`` cannot execute ``.cmd`` files
        directly — they must be run through ``cmd.exe /c``.
        """
        if sys.platform == "win32":
            return ["cmd.exe", "/c", *cmd]
        return cmd

    @staticmethod
    def _inject_history(instruction: str, history: list[dict]) -> str:
        """Append conversation history to instruction as text."""
        lines = ["# Recent Conversation"]
        for msg in history:
            role = msg.get("role", "user").capitalize()
            content = msg.get("content", "")
            if len(content) > 500:
                content = content[:500] + "..."
            lines.append(f"**{role}**: {content}")
        return instruction + "\n\n" + "\n".join(lines)

    def _parse_ndjson_event(self, event_data: dict) -> AgentEvent | None:
        """Parse a single NDJSON event from Codex CLI into an AgentEvent.

        Returns None for events that should be silently skipped (e.g. thread.started).
        """
        event_type = event_data.get("type", "")

        if event_type == "thread.started":
            thread_id = event_data.get("thread_id", "unknown")
            logger.info("Codex CLI thread: %s", thread_id)
            return None

        if event_type == "turn.started":
            logger.debug("Codex CLI turn started")
            return None

        if event_type == "turn.completed":
            usage = event_data.get("usage", {})
            if usage:
                return AgentEvent(
                    type="token_usage",
                    content="",
                    metadata={
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "cached_input_tokens": usage.get("cached_input_tokens", 0),
                    },
                )
            return None

        if event_type == "turn.failed":
            return AgentEvent(
                type="error",
                content=event_data.get("message", "Codex CLI turn failed"),
            )

        if event_type == "item.started":
            item = event_data.get("item", {})
            item_type = item.get("type", "")
            if item_type == "command_execution":
                cmd_str = item.get("command", "")
                return AgentEvent(
                    type="tool_use",
                    content=f"Running: {cmd_str}",
                    metadata={"name": "shell", "input": {"command": cmd_str}},
                )
            if item_type == "file_change":
                filename = item.get("filename", "unknown")
                return AgentEvent(
                    type="tool_use",
                    content=f"Editing: {filename}",
                    metadata={"name": "file_edit", "input": {"filename": filename}},
                )
            if item_type == "mcp_tool_call":
                tool_name = item.get("name", "mcp_tool")
                return AgentEvent(
                    type="tool_use",
                    content=f"MCP: {tool_name}",
                    metadata={"name": tool_name, "input": item.get("arguments", {})},
                )
            if item_type == "web_search":
                query = item.get("query", "")
                return AgentEvent(
                    type="tool_use",
                    content=f"Searching: {query}",
                    metadata={"name": "web_search", "input": {"query": query}},
                )
            return None

        if event_type == "item.completed":
            item = event_data.get("item", {})
            item_type = item.get("type", "")
            if item_type == "agent_message":
                text = item.get("text", "")
                if text:
                    return AgentEvent(type="message", content=text)
            elif item_type == "command_execution":
                output = item.get("output", "")
                return AgentEvent(
                    type="tool_result",
                    content=str(output)[:200],
                    metadata={"name": "shell"},
                )
            elif item_type == "file_change":
                filename = item.get("filename", "unknown")
                return AgentEvent(
                    type="tool_result",
                    content=f"Updated {filename}",
                    metadata={"name": "file_edit"},
                )
            elif item_type == "mcp_tool_call":
                tool_name = item.get("name", "mcp_tool")
                output = item.get("output", "")
                return AgentEvent(
                    type="tool_result",
                    content=str(output)[:200],
                    metadata={"name": tool_name},
                )
            elif item_type == "web_search":
                output = item.get("output", "")
                return AgentEvent(
                    type="tool_result",
                    content=str(output)[:200],
                    metadata={"name": "web_search"},
                )
            elif item_type == "reasoning":
                text = item.get("text", "")
                if text:
                    return AgentEvent(type="thinking", content=text)
            return None

        if event_type == "error":
            error_msg = event_data.get("message", "Unknown Codex CLI error")
            # Reconnection / fallback messages are transient — silently
            # suppress them so the user doesn't see infrastructure noise.
            if "Reconnecting" in error_msg or "Falling back" in error_msg:
                logger.debug("Codex CLI transient: %s", error_msg)
                return None
            return AgentEvent(type="error", content=error_msg)

        return None

    def _build_cmd(
        self,
        message: str,
        system_prompt: str | None = None,
        history: list[dict] | None = None,
    ) -> list[str]:
        """Build the full command line for the Codex CLI."""
        prompt_parts = []
        if system_prompt:
            prompt_parts.append(f"[System Instructions]\n{system_prompt}\n")
        if history:
            prompt_parts.append(self._inject_history("", history).strip())
        prompt_parts.append(message)
        full_prompt = "\n\n".join(prompt_parts)

        model = self.settings.codex_cli_model or "gpt-5.3-codex"

        return self._resolve_cmd([
            "codex",
            "exec",
            "--json",
            "--full-auto",
            "--model",
            model,
            full_prompt,
        ])

    async def run(
        self,
        message: str,
        *,
        system_prompt: str | None = None,
        history: list[dict] | None = None,
        session_key: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        if not self._cli_available:
            yield AgentEvent(
                type="error",
                content=(
                    "Codex CLI not found on PATH.\n\nInstall with: npm install -g @openai/codex"
                ),
            )
            return

        self._stop_flag = False
        cmd = self._build_cmd(message, system_prompt=system_prompt, history=history)

        try:
            # Try native async subprocess first
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except NotImplementedError:
            # Windows SelectorEventLoop (e.g. uvicorn reload mode) does not
            # support subprocess_exec. Fall back to synchronous Popen + thread.
            logger.info("asyncio subprocess not available, using Popen fallback")
            async for event in self._run_popen_fallback(cmd):
                yield event
            return

        try:
            if self._process.stdout is None:
                yield AgentEvent(type="error", content="Failed to capture Codex CLI stdout")
                return

            async for raw_line in self._process.stdout:
                if self._stop_flag:
                    break

                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                try:
                    event_data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                agent_event = self._parse_ndjson_event(event_data)
                if agent_event is not None:
                    yield agent_event

            # Wait for process to finish
            await self._process.wait()
            exit_code = self._process.returncode

            if exit_code and exit_code != 0 and not self._stop_flag:
                stderr_output = ""
                if self._process.stderr:
                    stderr_bytes = await self._process.stderr.read()
                    stderr_output = stderr_bytes.decode("utf-8", errors="replace").strip()

                base_msg = f"Codex CLI exited with code {exit_code}"
                if stderr_output:
                    base_msg += f": {stderr_output[:200]}"
                yield AgentEvent(type="error", content=base_msg)

            self._process = None
            yield AgentEvent(type="done", content="")

        except Exception as e:
            logger.error("Codex CLI error: %s: %s", type(e).__name__, e, exc_info=True)
            yield AgentEvent(
                type="error",
                content=f"Codex CLI error ({type(e).__name__}): {e}",
            )

    async def _run_popen_fallback(self, cmd: list[str]) -> AsyncIterator[AgentEvent]:
        """Run Codex CLI via subprocess.Popen when asyncio subprocess is unavailable.

        This is used on Windows when the event loop is a SelectorEventLoop
        (e.g. uvicorn ``--reload`` mode) which does not support
        ``asyncio.create_subprocess_exec``.

        A background thread reads stdout line-by-line and pushes NDJSON lines
        into an ``asyncio.Queue`` that this coroutine reads from.
        """
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        def _reader() -> tuple[int, str]:
            """Read stdout in a background thread, push lines to the queue."""
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                self._sync_process = proc

                assert proc.stdout is not None
                for raw_line in proc.stdout:
                    if self._stop_flag:
                        proc.kill()
                        break
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if line:
                        loop.call_soon_threadsafe(queue.put_nowait, line)

                proc.wait()
                stderr_output = ""
                if proc.stderr:
                    stderr_output = proc.stderr.read().decode("utf-8", errors="replace").strip()

                # Signal completion
                loop.call_soon_threadsafe(queue.put_nowait, None)
                return proc.returncode or 0, stderr_output
            except Exception as exc:
                logger.error("Popen reader thread error: %s", exc)
                loop.call_soon_threadsafe(queue.put_nowait, None)
                return 1, str(exc)

        # Start reader thread and run it concurrently
        future = loop.run_in_executor(None, _reader)

        # Consume lines from the queue as they arrive
        while True:
            line = await queue.get()
            if line is None:
                break  # Process finished

            try:
                event_data = json.loads(line)
            except json.JSONDecodeError:
                continue

            agent_event = self._parse_ndjson_event(event_data)
            if agent_event is not None:
                yield agent_event

        # Get final process result
        exit_code, stderr_output = await asyncio.wrap_future(future)
        self._sync_process = None

        if exit_code != 0 and not self._stop_flag:
            base_msg = f"Codex CLI exited with code {exit_code}"
            if stderr_output:
                base_msg += f": {stderr_output[:200]}"
            yield AgentEvent(type="error", content=base_msg)

        yield AgentEvent(type="done", content="")

    async def stop(self) -> None:
        self._stop_flag = True
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass
        if self._sync_process and self._sync_process.poll() is None:
            try:
                self._sync_process.terminate()
            except ProcessLookupError:
                pass

    async def get_status(self) -> dict[str, Any]:
        running = (
            (self._process is not None and self._process.returncode is None)
            or (self._sync_process is not None and self._sync_process.poll() is None)
        )
        return {
            "backend": "codex_cli",
            "cli_available": self._cli_available,
            "running": running,
            "model": self.settings.codex_cli_model or "gpt-5.3-codex",
        }

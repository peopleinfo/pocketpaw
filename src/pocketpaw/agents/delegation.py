# External Agent Delegation — subprocess-based execution of external agents.
# Created: 2026-02-07
# Part of Phase 2 Integration Ecosystem

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DelegationResult:
    """Result from an external agent execution."""

    agent: str
    output: str
    exit_code: int
    error: str = ""


class ExternalAgentDelegate:
    """Delegates tasks to external CLI agents via subprocess.

    Supported agents:
    - claude: Claude Code CLI (`claude --print --output-format json`)

    Security: This is a critical-trust operation since it launches
    a subprocess with full system access.
    """

    @staticmethod
    def is_available(agent: str) -> bool:
        """Check if an external agent CLI is installed."""
        if agent == "claude":
            return shutil.which("claude") is not None
        return False

    @staticmethod
    async def run(agent: str, prompt: str, timeout: float = 300) -> DelegationResult:
        """Run an external agent with a prompt and return the output.

        Args:
            agent: Agent identifier ("claude").
            prompt: Task prompt to send to the agent.
            timeout: Maximum execution time in seconds.

        Returns:
            DelegationResult with output and status.
        """
        if agent == "claude":
            return await ExternalAgentDelegate._run_claude(prompt, timeout)
        else:
            return DelegationResult(
                agent=agent,
                output="",
                exit_code=1,
                error=f"Unknown agent: {agent}",
            )

    @staticmethod
    async def _run_claude(prompt: str, timeout: float) -> DelegationResult:
        """Run Claude Code CLI."""
        if not shutil.which("claude"):
            return DelegationResult(
                agent="claude",
                output="",
                exit_code=1,
                error=(
                    "Claude Code CLI not found. "
                    "Install with: npm install -g @anthropic-ai/claude-code"
                ),
            )

        try:
            cmd = ["claude", "--print", "--output-format", "json", "-p", prompt]
            # On Windows, npm global installs create .cmd batch wrappers
            # that can't be executed directly by create_subprocess_exec.
            if sys.platform == "win32":
                cmd = ["cmd.exe", "/c", *cmd]

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                returncode = proc.returncode
            except NotImplementedError:
                # Windows SelectorEventLoop (e.g. uvicorn reload mode)
                # doesn't support async subprocess — use sync fallback.
                def _sync_run() -> subprocess.CompletedProcess:
                    return subprocess.run(
                        cmd,
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        timeout=timeout,
                    )

                result = await asyncio.get_event_loop().run_in_executor(None, _sync_run)
                stdout = result.stdout
                stderr = result.stderr
                returncode = result.returncode

            output = stdout.decode("utf-8", errors="replace")
            error = stderr.decode("utf-8", errors="replace")

            # Try to parse JSON output
            try:
                data = json.loads(output)
                if isinstance(data, dict) and "result" in data:
                    output = data["result"]
                elif isinstance(data, list):
                    # Extract text content from message blocks
                    texts = []
                    for item in data:
                        if isinstance(item, dict):
                            if item.get("type") == "text":
                                texts.append(item.get("text", ""))
                            elif "content" in item:
                                texts.append(str(item["content"]))
                    if texts:
                        output = "\n".join(texts)
            except (json.JSONDecodeError, KeyError):
                pass  # Use raw output

            return DelegationResult(
                agent="claude",
                output=output,
                exit_code=returncode or 0,
                error=error if returncode else "",
            )

        except TimeoutError:
            return DelegationResult(
                agent="claude",
                output="",
                exit_code=1,
                error=f"Claude Code CLI timed out after {timeout}s",
            )
        except Exception as e:
            return DelegationResult(
                agent="claude",
                output="",
                exit_code=1,
                error=str(e),
            )

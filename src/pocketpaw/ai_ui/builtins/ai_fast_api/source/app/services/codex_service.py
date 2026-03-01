"""Codex CLI backend — uses ChatGPT OAuth login from `codex login`."""

import asyncio
import json
import os
import platform
import shutil
import time
import uuid
from pathlib import Path
from typing import AsyncGenerator, List

from ..config import settings
from ..models import (
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionStreamChoice,
    ChatCompletionStreamResponse,
    ChatCompletionUsage,
    ChatMessage,
    ImageGenerationRequest,
    ImageGenerationResponse,
    MessageRole,
    ModelInfo,
    ProviderInfo,
)
from ..utils.logger import logger
from . import BaseLLMService


def _resolve_codex_bin(explicit_bin: str = "") -> str | None:
    if explicit_bin:
        candidate = Path(explicit_bin).expanduser()
        if candidate.exists():
            return str(candidate)

    path_bin = shutil.which("codex")
    if path_bin:
        return path_bin

    if platform.system() == "Darwin":
        for candidate in ("/opt/homebrew/bin/codex", "/usr/local/bin/codex"):
            if Path(candidate).exists():
                return candidate
    elif platform.system() == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidate = Path(local_app_data) / "Programs" / "codex" / "codex.exe"
            if candidate.exists():
                return str(candidate)
    else:
        for candidate in ("/usr/local/bin/codex", "/usr/bin/codex"):
            if Path(candidate).exists():
                return candidate

    return None


def _extract_agent_messages(stdout_text: str) -> tuple[list[str], str]:
    messages: list[str] = []
    last_error = ""

    for line in stdout_text.splitlines():
        clean = line.strip()
        if not clean.startswith("{"):
            continue
        try:
            payload = json.loads(clean)
        except json.JSONDecodeError:
            continue

        event_type = payload.get("type")
        if event_type == "item.completed":
            item = payload.get("item") or {}
            if item.get("type") == "agent_message":
                text = (item.get("text") or "").strip()
                if text:
                    messages.append(text)
        elif event_type in {"turn.failed", "error"}:
            last_error = str(payload.get("message") or payload)

    return messages, last_error


class CodexService(BaseLLMService):
    """LLM service backed by OpenAI Codex CLI OAuth session."""

    def __init__(self):
        self._initialized = False
        self._codex_bin = _resolve_codex_bin(settings.codex_bin)
        self._auth_logged_in = False
        self._workdir = Path(__file__).resolve().parents[2]
        self._host_home = os.environ.get("POCKETPAW_HOST_HOME", "").strip()

    def _codex_env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self._host_home:
            env["HOME"] = self._host_home
            env.setdefault("CODEX_HOME", str(Path(self._host_home) / ".codex"))
        path_parts = env.get("PATH", "").split(os.pathsep) if env.get("PATH") else []
        for candidate in ("/opt/homebrew/bin", "/usr/local/bin"):
            if candidate not in path_parts and Path(candidate).exists():
                path_parts.insert(0, candidate)
        if path_parts:
            env["PATH"] = os.pathsep.join(path_parts)
        return env

    async def initialize(self):
        if not self._codex_bin:
            logger.warning("Codex backend selected but codex CLI is not installed")
            self._initialized = True
            return

        self._auth_logged_in = await self._check_auth_status()
        if not self._auth_logged_in:
            logger.warning(
                "Codex CLI is installed but not logged in. Use `codex login --device-auth`."
            )
        self._initialized = True

    async def cleanup(self):
        self._initialized = False

    async def _check_auth_status(self) -> bool:
        if not self._codex_bin:
            return False
        try:
            proc = await asyncio.create_subprocess_exec(
                self._codex_bin,
                "login",
                "status",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._workdir),
                env=self._codex_env(),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")
            text = stdout_text + "\n" + stderr_text
            ok = proc.returncode == 0 and "Logged in" in text
            if not ok:
                logger.info(
                    "Codex login status not authenticated (rc=%s, stdout=%r, stderr=%r)",
                    proc.returncode,
                    stdout_text[:200],
                    stderr_text[:200],
                )
            return ok
        except Exception:
            return False

    async def _run_codex_completion(self, request: ChatCompletionRequest) -> str:
        if not self._codex_bin:
            raise RuntimeError("codex CLI not found. Install `@openai/codex` first.")

        if not self._auth_logged_in and not await self._check_auth_status():
            raise RuntimeError(
                "Codex OAuth is not connected. Run Codex OAuth login in AI Fast API settings."
            )

        prompt_lines = [
            "You are an OpenAI-compatible chat completion assistant.",
            "Return only the assistant reply text, no extra wrappers.",
            "",
            "Conversation:",
        ]
        for msg in request.messages:
            prompt_lines.append(f"{msg.role.value.upper()}: {msg.content}")
        prompt_lines.append("ASSISTANT:")
        prompt = "\n".join(prompt_lines)

        model = request.model or settings.codex_model or "gpt-5"
        cmd = [
            self._codex_bin,
            "exec",
            "--json",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--model",
            model,
            prompt,
        ]
        logger.info("Codex completion request with model: %s", model)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._workdir),
            env=self._codex_env(),
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=settings.codex_timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise RuntimeError(f"Codex timeout after {settings.codex_timeout}s")

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace").strip()

        messages, last_error = _extract_agent_messages(stdout_text)
        if proc.returncode != 0:
            detail = stderr_text or last_error or f"codex exited with code {proc.returncode}"
            raise RuntimeError(detail)
        if not messages:
            detail = last_error or stderr_text or "Codex returned empty response"
            raise RuntimeError(detail)

        self._auth_logged_in = True
        return messages[-1]

    async def create_chat_completion(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        try:
            content = await self._run_codex_completion(request)
            completion_id = f"chatcmpl-{uuid.uuid4().hex[:29]}"
            return ChatCompletionResponse(
                id=completion_id,
                object="chat.completion",
                created=int(time.time()),
                model=request.model or settings.codex_model or "gpt-5",
                choices=[
                    ChatCompletionChoice(
                        index=0,
                        message=ChatMessage(role=MessageRole.ASSISTANT, content=content),
                        finish_reason="stop",
                    )
                ],
                usage=ChatCompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            )
        except Exception as e:
            logger.error("Error in Codex chat completion: %s", e)
            raise

    async def create_chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncGenerator[str, None]:
        try:
            response = await self.create_chat_completion(request)
            chunk = ChatCompletionStreamResponse(
                id=response.id,
                object="chat.completion.chunk",
                created=int(time.time()),
                model=response.model,
                choices=[
                    ChatCompletionStreamChoice(
                        index=0,
                        delta={
                            "role": "assistant",
                            "content": response.choices[0].message.content,
                        },
                        finish_reason=None,
                    )
                ],
            )
            yield f"data: {chunk.model_dump_json()}\n\n"
            final = ChatCompletionStreamResponse(
                id=response.id,
                object="chat.completion.chunk",
                created=int(time.time()),
                model=response.model,
                choices=[
                    ChatCompletionStreamChoice(
                        index=0,
                        delta={},
                        finish_reason="stop",
                    )
                ],
            )
            yield f"data: {final.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("Error in Codex streaming completion: %s", e)
            error_response = {
                "error": {
                    "message": str(e),
                    "type": "server_error",
                    "code": "internal_error",
                }
            }
            yield f"data: {json.dumps(error_response)}\n\n"

    async def create_image_generation(
        self, request: ImageGenerationRequest
    ) -> ImageGenerationResponse:
        raise NotImplementedError("Codex backend does not support image generation.")

    async def get_models(self) -> List[ModelInfo]:
        now = int(time.time())
        raw_models = [
            settings.codex_model or "gpt-5",
            "gpt-5",
            "gpt-5-codex",
            "gpt-5.3-codex",
            "o3",
            "o4-mini",
        ]
        models: list[ModelInfo] = []
        seen: set[str] = set()
        for model_id in raw_models:
            m = model_id.strip()
            if not m or m in seen:
                continue
            seen.add(m)
            models.append(ModelInfo(id=m, created=now, owned_by="codex"))
        return models

    async def get_providers(self) -> List[ProviderInfo]:
        self._auth_logged_in = await self._check_auth_status()
        return [
            ProviderInfo(
                id="CodexOAuth",
                url="https://auth.openai.com/codex/device",
                models=[m.id for m in await self.get_models()],
                params={
                    "supports_stream": True,
                    "oauth": True,
                    "logged_in": self._auth_logged_in,
                    "no_auth": False,
                },
            )
        ]

"""Gemini CLI backend — uses Google OAuth from `@google/gemini-cli`."""

import asyncio
import json
import os
import platform
import re
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


def _resolve_gemini_command(explicit_bin: str = "") -> list[str] | None:
    if explicit_bin:
        candidate = Path(explicit_bin).expanduser()
        if candidate.exists():
            return [str(candidate)]

    gemini_bin = shutil.which("gemini")
    if gemini_bin:
        return [gemini_bin]

    if platform.system() == "Darwin":
        for candidate in ("/opt/homebrew/bin/gemini", "/usr/local/bin/gemini"):
            if Path(candidate).exists():
                return [candidate]
    elif platform.system() == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidate = Path(local_app_data) / "Programs" / "gemini" / "gemini.exe"
            if candidate.exists():
                return [str(candidate)]
    else:
        for candidate in ("/usr/local/bin/gemini", "/usr/bin/gemini"):
            if Path(candidate).exists():
                return [candidate]

    npx_bin = shutil.which("npx")
    if npx_bin:
        return [npx_bin, "-y", "@google/gemini-cli"]
    for candidate in ("/opt/homebrew/bin/npx", "/usr/local/bin/npx", "/usr/bin/npx"):
        if Path(candidate).exists():
            return [candidate, "-y", "@google/gemini-cli"]
    return None


def _extract_gemini_json(stdout_text: str) -> dict:
    candidates: list[str] = []
    for line in stdout_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            candidates.append(stripped)

    if not candidates:
        match = re.search(r"(\{[\s\S]*\})", stdout_text, re.S)
        if match:
            candidates.append(match.group(1))

    for raw in reversed(candidates):
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            continue
    return {}


def _extract_gemini_result(stdout_text: str) -> tuple[str | None, str]:
    payload = _extract_gemini_json(stdout_text)
    if not payload:
        return None, ""

    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        return None, message

    response = str(payload.get("response") or "").strip()
    return (response if response else None), ""


class GeminiService(BaseLLMService):
    """LLM service backed by Gemini CLI OAuth session."""

    def __init__(self):
        self._initialized = False
        self._gemini_cmd = _resolve_gemini_command(settings.gemini_bin)
        self._auth_logged_in = False
        self._workdir = Path(__file__).resolve().parents[2]
        self._host_home = os.environ.get("POCKETPAW_HOST_HOME", "").strip()

    def _gemini_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["GOOGLE_GENAI_USE_GCA"] = "true"
        if self._host_home:
            env["HOME"] = self._host_home
        path_parts = env.get("PATH", "").split(os.pathsep) if env.get("PATH") else []
        for candidate in ("/opt/homebrew/bin", "/usr/local/bin"):
            if candidate not in path_parts and Path(candidate).exists():
                path_parts.insert(0, candidate)
        if path_parts:
            env["PATH"] = os.pathsep.join(path_parts)
        return env

    def _creds_path(self) -> Path:
        home = self._host_home or str(Path.home())
        return Path(home) / ".gemini" / "oauth_creds.json"

    async def initialize(self):
        if not self._gemini_cmd:
            logger.warning("Gemini backend selected but gemini CLI is not installed")
            self._initialized = True
            return

        self._auth_logged_in = await self._check_auth_status()
        if not self._auth_logged_in:
            logger.warning(
                "Gemini CLI is installed but not logged in. Start Gemini OAuth in settings."
            )
        self._initialized = True

    async def cleanup(self):
        self._initialized = False

    async def _check_auth_status(self) -> bool:
        creds_path = self._creds_path()
        if not creds_path.exists():
            return False
        try:
            creds = json.loads(creds_path.read_text(encoding="utf-8"))
        except Exception:
            return False

        access_token = str(creds.get("access_token", "")).strip()
        if not access_token:
            return False

        expiry = creds.get("expiry_date")
        if isinstance(expiry, (int, float)) and expiry > 0:
            if expiry <= (time.time() * 1000):
                return False
        return True

    async def _run_gemini_completion(self, request: ChatCompletionRequest) -> str:
        if not self._gemini_cmd:
            raise RuntimeError("gemini CLI not found. Install @google/gemini-cli first.")

        if not self._auth_logged_in and not await self._check_auth_status():
            raise RuntimeError(
                "Gemini OAuth is not connected. Run Gemini OAuth login in AI Fast API settings."
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

        model = request.model or settings.gemini_model or "gemini-2.5-flash"
        cmd = [
            *self._gemini_cmd,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--model",
            model,
        ]
        logger.info("Gemini completion request with model: %s", model)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._workdir),
            env=self._gemini_env(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=settings.gemini_timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise RuntimeError(f"Gemini timeout after {settings.gemini_timeout}s")

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        content, parse_error = _extract_gemini_result(stdout_text)

        if proc.returncode != 0:
            detail = parse_error or stderr_text or f"gemini exited with code {proc.returncode}"
            raise RuntimeError(detail)
        if not content:
            detail = parse_error or stderr_text or "Gemini returned empty response"
            raise RuntimeError(detail)

        self._auth_logged_in = True
        return content

    async def create_chat_completion(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        try:
            content = await self._run_gemini_completion(request)
            completion_id = f"chatcmpl-{uuid.uuid4().hex[:29]}"
            return ChatCompletionResponse(
                id=completion_id,
                object="chat.completion",
                created=int(time.time()),
                model=request.model or settings.gemini_model or "gemini-2.5-flash",
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
            logger.error("Error in Gemini chat completion: %s", e)
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
            logger.error("Error in Gemini streaming completion: %s", e)
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
        raise NotImplementedError("Gemini backend does not support image generation.")

    async def get_models(self) -> List[ModelInfo]:
        now = int(time.time())
        raw_models = [
            settings.gemini_model or "gemini-2.5-flash",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
        ]
        models: list[ModelInfo] = []
        seen: set[str] = set()
        for model_id in raw_models:
            m = model_id.strip()
            if not m or m in seen:
                continue
            seen.add(m)
            models.append(ModelInfo(id=m, created=now, owned_by="google"))
        return models

    async def get_providers(self) -> List[ProviderInfo]:
        self._auth_logged_in = await self._check_auth_status()
        return [
            ProviderInfo(
                id="GeminiOAuth",
                url="https://accounts.google.com",
                models=[m.id for m in await self.get_models()],
                params={
                    "supports_stream": True,
                    "oauth": True,
                    "logged_in": self._auth_logged_in,
                    "no_auth": False,
                },
            )
        ]

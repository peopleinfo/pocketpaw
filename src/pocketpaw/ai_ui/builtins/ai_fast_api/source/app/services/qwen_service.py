"""Qwen CLI backend — uses Qwen OAuth from `@qwen-code/qwen-code`."""

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


def _resolve_qwen_command(explicit_bin: str = "") -> list[str] | None:
    if explicit_bin:
        candidate = Path(explicit_bin).expanduser()
        if candidate.exists():
            return [str(candidate)]

    qwen_bin = shutil.which("qwen")
    if qwen_bin:
        return [qwen_bin]

    if platform.system() == "Darwin":
        for candidate in ("/opt/homebrew/bin/qwen", "/usr/local/bin/qwen"):
            if Path(candidate).exists():
                return [candidate]
    elif platform.system() == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidate = Path(local_app_data) / "Programs" / "qwen" / "qwen.exe"
            if candidate.exists():
                return [str(candidate)]
    else:
        for candidate in ("/usr/local/bin/qwen", "/usr/bin/qwen"):
            if Path(candidate).exists():
                return [candidate]

    npx_bin = shutil.which("npx")
    if npx_bin:
        return [npx_bin, "-y", "@qwen-code/qwen-code"]
    for candidate in ("/opt/homebrew/bin/npx", "/usr/local/bin/npx", "/usr/bin/npx"):
        if Path(candidate).exists():
            return [candidate, "-y", "@qwen-code/qwen-code"]
    return None


def _extract_qwen_events(text: str) -> list[dict]:
    candidates: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            candidates.append(stripped)

    if not candidates:
        match = re.search(r"(\[\s*\{.*\}\s*\])", text, re.S)
        if match:
            candidates.append(match.group(1))

    for raw in reversed(candidates):
        try:
            payload = json.loads(raw)
            if isinstance(payload, list):
                return payload
        except json.JSONDecodeError:
            continue
    return []


def _extract_qwen_result(stdout_text: str) -> tuple[str | None, str]:
    events = _extract_qwen_events(stdout_text)
    assistant_texts: list[str] = []
    last_error = ""

    for event in events:
        event_type = event.get("type")
        if event_type == "assistant":
            message = event.get("message") or {}
            for chunk in message.get("content") or []:
                if chunk.get("type") == "text":
                    text = str(chunk.get("text") or "").strip()
                    if text:
                        assistant_texts.append(text)
        elif event_type == "result":
            subtype = str(event.get("subtype") or "")
            if event.get("is_error") or subtype.startswith("error"):
                err = event.get("error") or {}
                last_error = str(err.get("message") or event.get("result") or "").strip()
            elif subtype == "success":
                text = str(event.get("result") or "").strip()
                if text:
                    return text, last_error

    if assistant_texts:
        return assistant_texts[-1], last_error
    return None, last_error


class QwenService(BaseLLMService):
    """LLM service backed by Qwen CLI OAuth session."""

    def __init__(self):
        self._initialized = False
        self._qwen_cmd = _resolve_qwen_command(settings.qwen_bin)
        self._auth_logged_in = False
        self._workdir = Path(__file__).resolve().parents[2]
        self._host_home = os.environ.get("POCKETPAW_HOST_HOME", "").strip()

    def _qwen_env(self) -> dict[str, str]:
        env = dict(os.environ)
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
        return Path(home) / ".qwen" / "oauth_creds.json"

    async def initialize(self):
        if not self._qwen_cmd:
            logger.warning("Qwen backend selected but qwen CLI is not installed")
            self._initialized = True
            return

        self._auth_logged_in = await self._check_auth_status()
        if not self._auth_logged_in:
            logger.warning("Qwen CLI is installed but not logged in. Start Qwen OAuth in settings.")
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

    async def _run_qwen_completion(self, request: ChatCompletionRequest) -> str:
        if not self._qwen_cmd:
            raise RuntimeError("qwen CLI not found. Install @qwen-code/qwen-code first.")

        if not self._auth_logged_in and not await self._check_auth_status():
            raise RuntimeError(
                "Qwen OAuth is not connected. Run Qwen OAuth login in AI Fast API settings."
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

        model = request.model or settings.qwen_model or "qwen3-coder-plus"
        cmd = [
            *self._qwen_cmd,
            "--auth-type",
            "qwen-oauth",
            "--output-format",
            "json",
            "--model",
            model,
            prompt,
        ]
        logger.info("Qwen completion request with model: %s", model)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._workdir),
            env=self._qwen_env(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=settings.qwen_timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise RuntimeError(f"Qwen timeout after {settings.qwen_timeout}s")

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        content, parse_error = _extract_qwen_result(stdout_text)

        if proc.returncode != 0:
            detail = parse_error or stderr_text or f"qwen exited with code {proc.returncode}"
            raise RuntimeError(detail)
        if not content:
            detail = parse_error or stderr_text or "Qwen returned empty response"
            raise RuntimeError(detail)

        self._auth_logged_in = True
        return content

    async def create_chat_completion(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        try:
            content = await self._run_qwen_completion(request)
            completion_id = f"chatcmpl-{uuid.uuid4().hex[:29]}"
            return ChatCompletionResponse(
                id=completion_id,
                object="chat.completion",
                created=int(time.time()),
                model=request.model or settings.qwen_model or "qwen3-coder-plus",
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
            logger.error("Error in Qwen chat completion: %s", e)
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
            logger.error("Error in Qwen streaming completion: %s", e)
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
        raise NotImplementedError("Qwen backend does not support image generation.")

    async def get_models(self) -> List[ModelInfo]:
        now = int(time.time())
        raw_models = [
            settings.qwen_model or "qwen3-coder-plus",
            "qwen3-coder-plus",
            "qwen3-max-preview",
            "qwen3-235b-a22b-instruct-2507",
            "coder-model",
        ]
        models: list[ModelInfo] = []
        seen: set[str] = set()
        for model_id in raw_models:
            m = model_id.strip()
            if not m or m in seen:
                continue
            seen.add(m)
            models.append(ModelInfo(id=m, created=now, owned_by="qwen"))
        return models

    async def get_providers(self) -> List[ProviderInfo]:
        self._auth_logged_in = await self._check_auth_status()
        return [
            ProviderInfo(
                id="QwenOAuth",
                url="https://chat.qwen.ai/authorize",
                models=[m.id for m in await self.get_models()],
                params={
                    "supports_stream": True,
                    "oauth": True,
                    "logged_in": self._auth_logged_in,
                    "no_auth": False,
                },
            )
        ]

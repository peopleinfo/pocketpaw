"""Auto-rotate backend — failover across multiple providers/backends."""

import json
import os
import time
from typing import AsyncGenerator, List

from ..config import settings
from ..models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionStreamChoice,
    ChatCompletionStreamResponse,
    ImageGenerationRequest,
    ImageGenerationResponse,
    ModelInfo,
    ProviderInfo,
)
from ..utils.logger import logger
from . import BaseLLMService


def _parse_rotate_backends(raw: str) -> list[str]:
    valid = {"g4f", "ollama", "codex", "qwen", "gemini"}
    result: list[str] = []
    for item in (raw or "").split(","):
        backend = item.strip().lower()
        if not backend or backend not in valid or backend in result:
            continue
        result.append(backend)
    if not result:
        return ["g4f", "ollama", "codex", "qwen", "gemini"]
    return result


def _build_service(backend: str) -> BaseLLMService:
    if backend == "g4f":
        from .g4f_service import G4FService

        return G4FService()
    if backend == "ollama":
        from .ollama_service import OllamaService

        return OllamaService()
    if backend == "codex":
        from .codex_service import CodexService

        return CodexService()
    if backend == "qwen":
        from .qwen_service import QwenService

        return QwenService()
    if backend == "gemini":
        from .gemini_service import GeminiService

        return GeminiService()
    raise ValueError(f"Unsupported auto-rotate backend: {backend}")


class AutoRotateService(BaseLLMService):
    """Proxy rotator that retries by rotating through configured backends."""

    def __init__(self):
        self._initialized = False
        self._backend_chain = _parse_rotate_backends(settings.auto_rotate_backends)
        self._max_rotate_retry = max(1, int(settings.auto_max_rotate_retry or 4))
        self._services: dict[str, BaseLLMService] = {}
        self._round_robin_seed = 0

    async def initialize(self):
        self._services.clear()
        for backend in self._backend_chain:
            try:
                svc = _build_service(backend)
                await svc.initialize()
                self._services[backend] = svc
            except Exception as e:
                logger.warning("Auto backend failed to initialize '%s': %s", backend, e)
        if not self._services:
            raise RuntimeError("Auto backend has no available providers/backends")
        self._initialized = True
        logger.info(
            "Auto rotate initialized with backends=%s max_retry=%s",
            ",".join(self._backend_chain),
            self._max_rotate_retry,
        )

    async def cleanup(self):
        for backend, svc in self._services.items():
            try:
                await svc.cleanup()
            except Exception as e:
                logger.warning("Auto cleanup failed for '%s': %s", backend, e)
        self._services.clear()
        self._initialized = False

    def _ordered_backends(self) -> list[str]:
        available = [b for b in self._backend_chain if b in self._services]
        if not available:
            return []
        offset = self._round_robin_seed % len(available)
        self._round_robin_seed += 1
        return available[offset:] + available[:offset]

    async def _is_backend_active(self, backend: str, svc: BaseLLMService) -> bool:
        try:
            providers = await svc.get_providers()
        except Exception as e:
            logger.debug("Auto rotate could not fetch providers for '%s': %s", backend, e)
            return False

        if not providers:
            return True

        for provider in providers:
            params = provider.params or {}
            oauth = bool(params.get("oauth"))
            logged_in = bool(params.get("logged_in"))
            no_auth = bool(params.get("no_auth"))

            if oauth:
                if logged_in:
                    return True
                continue
            if no_auth:
                return True

            # If backend does not declare oauth/no_auth flags, assume active.
            if "oauth" not in params and "no_auth" not in params:
                return True

        return False

    async def _active_backends(self) -> list[str]:
        active: list[str] = []
        for backend in self._ordered_backends():
            svc = self._services.get(backend)
            if svc is None:
                continue
            if await self._is_backend_active(backend, svc):
                active.append(backend)
        return active

    @staticmethod
    def _default_model_for_backend(backend: str) -> str:
        if backend == "ollama":
            return settings.auto_ollama_model or os.getenv("OLLAMA_DEFAULT_MODEL", "llama3.1")
        if backend == "codex":
            return settings.auto_codex_model or settings.codex_model or "gpt-5"
        if backend == "qwen":
            return settings.auto_qwen_model or settings.qwen_model or "qwen3-coder-plus"
        if backend == "gemini":
            return settings.auto_gemini_model or settings.gemini_model or "gemini-2.5-flash"
        return settings.auto_g4f_model or settings.g4f_model or "gpt-4o-mini"

    def _prepare_request(
        self, request: ChatCompletionRequest, backend: str, attempt_index: int
    ) -> ChatCompletionRequest:
        # In auto mode, each backend uses its own configured default model.
        model = self._default_model_for_backend(backend)
        update = {"model": model}
        if backend != "g4f":
            # Non-G4F backends ignore g4f-specific provider hints.
            update["provider"] = None
        return request.model_copy(update=update)

    async def create_chat_completion(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        backends = await self._active_backends()
        if not backends:
            raise RuntimeError("Auto rotate has no active backends (login may be required)")

        errors: list[str] = []
        for attempt in range(self._max_rotate_retry):
            backend = backends[attempt % len(backends)]
            svc = self._services[backend]
            req_for_backend = self._prepare_request(request, backend, attempt)
            try:
                logger.info(
                    "Auto rotate attempt %s/%s -> backend=%s model=%s",
                    attempt + 1,
                    self._max_rotate_retry,
                    backend,
                    req_for_backend.model,
                )
                return await svc.create_chat_completion(req_for_backend)
            except Exception as e:
                msg = str(e) or e.__class__.__name__
                logger.warning(
                    "Auto rotate backend '%s' failed on attempt %s/%s: %s",
                    backend,
                    attempt + 1,
                    self._max_rotate_retry,
                    msg,
                )
                errors.append(f"{backend}: {msg}")

        raise RuntimeError(
            "Auto rotate exhausted retries. "
            + (" | ".join(errors[-self._max_rotate_retry :]) if errors else "No backend errors.")
        )

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
            logger.error("Error in AutoRotate streaming completion: %s", e)
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
        # Image generation is primarily handled by G4F.
        g4f = self._services.get("g4f")
        if g4f is None:
            raise NotImplementedError("Auto rotate image generation requires g4f backend enabled")
        return await g4f.create_image_generation(request)

    async def get_models(self) -> List[ModelInfo]:
        merged: list[ModelInfo] = []
        seen: set[str] = set()
        for backend in self._backend_chain:
            svc = self._services.get(backend)
            if svc is None:
                continue
            try:
                models = await svc.get_models()
            except Exception:
                continue
            for model in models:
                if model.id in seen:
                    continue
                seen.add(model.id)
                merged.append(model)
        return merged

    async def get_providers(self) -> List[ProviderInfo]:
        active_backends = await self._active_backends()
        providers: list[ProviderInfo] = [
            ProviderInfo(
                id="AutoRotate",
                url=None,
                models=[m.id for m in await self.get_models()],
                params={
                    "supports_stream": True,
                    "rotator": True,
                    "max_retry": self._max_rotate_retry,
                    "backends": [b for b in self._backend_chain if b in self._services],
                    "active_backends": active_backends,
                },
            )
        ]
        for backend in self._backend_chain:
            svc = self._services.get(backend)
            if svc is None:
                continue
            try:
                providers.extend(await svc.get_providers())
            except Exception:
                continue
        return providers

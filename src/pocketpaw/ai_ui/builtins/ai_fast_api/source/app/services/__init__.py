"""Service layer — provider-agnostic LLM interface.

To add a new backend beside G4F:
  1. Create a module (e.g. ``ollama_service.py``)
  2. Subclass ``BaseLLMService``
  3. Register it in ``get_service()`` below
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import AsyncGenerator, List

from ..models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ImageGenerationRequest,
    ImageGenerationResponse,
    ModelInfo,
    ProviderInfo,
)

logger = logging.getLogger(__name__)


class BaseLLMService(ABC):
    """Abstract base class every LLM backend must implement."""

    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def cleanup(self) -> None: ...

    @abstractmethod
    async def create_chat_completion(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse: ...

    @abstractmethod
    async def create_chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncGenerator[str, None]: ...

    @abstractmethod
    async def create_image_generation(
        self, request: ImageGenerationRequest
    ) -> ImageGenerationResponse: ...

    @abstractmethod
    async def get_models(self) -> List[ModelInfo]: ...

    @abstractmethod
    async def get_providers(self) -> List[ProviderInfo]: ...


_active_service: BaseLLMService | None = None


def get_service() -> BaseLLMService:
    """Return the active LLM service singleton.

    Defaults to G4F.  To swap backend, set ``LLM_BACKEND``
    env var (e.g. ``ollama``, ``litellm``) before startup.
    """
    global _active_service  # noqa: PLW0603
    if _active_service is not None:
        return _active_service

    import os

    backend = os.getenv("LLM_BACKEND", "g4f").lower()

    if backend == "g4f":
        from .g4f_service import G4FService

        _active_service = G4FService()
    elif backend == "ollama":
        from .ollama_service import OllamaService

        _active_service = OllamaService()
    elif backend == "codex":
        from .codex_service import CodexService

        _active_service = CodexService()
    else:
        raise ValueError(
            f"Unknown LLM_BACKEND '{backend}'. "
            "Available: 'g4f', 'ollama', 'codex'. Implement BaseLLMService to add more."
        )

    return _active_service

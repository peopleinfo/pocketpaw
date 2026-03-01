"""Ollama backend \u2014 implements BaseLLMService using OpenAI client pointing to local Ollama."""

import json
import os
import time
import uuid
from typing import AsyncGenerator, List, Optional

from openai import AsyncOpenAI
import httpx

from ..models import (
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionStreamChoice,
    ChatCompletionStreamResponse,
    ChatCompletionUsage,
    ChatMessage,
    ImageData,
    ImageGenerationRequest,
    ImageGenerationResponse,
    MessageRole,
    ModelInfo,
    ProviderInfo,
)
from ..utils.logger import logger
from . import BaseLLMService


class OllamaService(BaseLLMService):
    """LLM service backed by local Ollama via OpenAI compatibility layer."""

    def __init__(self):
        self._models_cache: Optional[List[ModelInfo]] = None
        self._cache_timestamp = 0
        self._cache_ttl = 300
        self._initialized = False

        # Connect to Ollama's OpenAI-compatible endpoint
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
        # Ensure it has trailing slash for httpx
        if not base_url.endswith("/"):
            base_url += "/"

        self.base_url = base_url
        self._client = AsyncOpenAI(
            base_url=self.base_url,
            api_key="ollama",  # Required but ignored by ollama
        )

    async def initialize(self):
        try:
            logger.info(f"Initializing Ollama service against {self.base_url}...")
            await self.get_models()
            self._initialized = True
            logger.info("Ollama service initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Ollama service: {e}")
            self._initialized = True  # Proceed anyway just in case ollama boots later

    async def cleanup(self):
        try:
            logger.info("Cleaning up Ollama service...")
            self._models_cache = None
            self._initialized = False
            if hasattr(self._client, "close"):
                await self._client.close()
            logger.info("Ollama service cleanup completed")
        except Exception as e:
            logger.error(f"Error during Ollama service cleanup: {e}")

    def _is_cache_valid(self) -> bool:
        if self._cache_timestamp == 0:
            return False
        return time.time() - self._cache_timestamp < self._cache_ttl

    async def create_chat_completion(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        try:
            logger.info(f"Ollama chat completion with model: {request.model}")
            messages = [
                {"role": msg.role.value, "content": msg.content} for msg in request.messages
            ]

            kwargs = {
                "model": request.model,
                "messages": messages,
                "stream": False,
            }
            if request.max_tokens:
                kwargs["max_tokens"] = request.max_tokens

            response = await self._client.chat.completions.create(**kwargs)

            completion_id = response.id if response.id else f"chatcmpl-{uuid.uuid4().hex[:29]}"

            return ChatCompletionResponse(
                id=completion_id,
                object="chat.completion",
                created=response.created or int(time.time()),
                model=response.model or request.model,
                choices=[
                    ChatCompletionChoice(
                        index=c.index,
                        message=ChatMessage(
                            role=MessageRole(c.message.role), content=c.message.content or ""
                        ),
                        finish_reason=c.finish_reason,
                    )
                    for c in response.choices
                ],
                usage=ChatCompletionUsage(
                    prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                    completion_tokens=response.usage.completion_tokens if response.usage else 0,
                    total_tokens=response.usage.total_tokens if response.usage else 0,
                ),
            )
        except Exception as e:
            logger.error(f"Error in Ollama chat completion: {e}", exc_info=True)
            raise

    async def create_chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncGenerator[str, None]:
        try:
            logger.info(f"Ollama streaming chat completion with model: {request.model}")
            messages = [
                {"role": msg.role.value, "content": msg.content} for msg in request.messages
            ]

            kwargs = {
                "model": request.model,
                "messages": messages,
                "stream": True,
            }
            if request.max_tokens:
                kwargs["max_tokens"] = request.max_tokens

            stream = await self._client.chat.completions.create(**kwargs)

            async for chunk in stream:
                # Need to convert openai's chunk to our model
                stream_response = ChatCompletionStreamResponse(
                    id=chunk.id or f"chatcmpl-{uuid.uuid4().hex[:29]}",
                    object="chat.completion.chunk",
                    created=chunk.created or int(time.time()),
                    model=chunk.model or request.model,
                    choices=[
                        ChatCompletionStreamChoice(
                            index=c.index,
                            delta={"role": c.delta.role, "content": c.delta.content}
                            if getattr(c.delta, "content", None) is not None
                            else {},
                            finish_reason=c.finish_reason,
                        )
                        for c in chunk.choices
                    ],
                )
                yield f"data: {stream_response.model_dump_json(exclude_none=True)}\n\n"

            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"Error in Ollama streaming chat completion: {e}")
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
        # Ollama does not directly support image generation natively inside the OpenAI chat completions layer
        # However, it might in the future. We can throw an informative error or simply try
        raise NotImplementedError(
            "Ollama does not natively support image generation. Use G4F for images."
        )

    async def get_models(self) -> List[ModelInfo]:
        if self._is_cache_valid() and self._models_cache:
            return self._models_cache
        try:
            logger.info("Fetching models from local Ollama")
            models = await self._client.models.list()

            result = []
            for m in models.data:
                result.append(
                    ModelInfo(
                        id=m.id,
                        created=m.created or int(time.time()),
                        owned_by=m.owned_by or "ollama",
                    )
                )

            self._models_cache = result
            self._cache_timestamp = time.time()
            return result
        except Exception as e:
            logger.error(f"Error fetching Ollama models: {e}")
            return [
                ModelInfo(id="No Ollama models found", created=int(time.time()), owned_by="ollama")
            ]

    async def get_providers(self) -> List[ProviderInfo]:
        # Ollama manages its own models locally
        return [
            ProviderInfo(
                id="Local Ollama",
                url=self.base_url,
                models=[m.id for m in (self._models_cache or [])],
                params={"supports_stream": True, "no_auth": True},
            )
        ]

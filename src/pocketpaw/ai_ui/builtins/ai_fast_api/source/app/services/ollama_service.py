"""Ollama backend - implements BaseLLMService via Ollama's local HTTP API."""

import json
import os
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from urllib.parse import urlparse

import httpx

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


class OllamaService(BaseLLMService):
    """LLM service backed by Ollama endpoints (local or cloud)."""

    def __init__(self):
        self._models_cache: list[ModelInfo] | None = None
        self._cache_timestamp = 0
        self._cache_ttl = 300
        self._initialized = False

        deployment = os.environ.get("OLLAMA_DEPLOYMENT", "local").strip().lower()
        if deployment not in {"local", "cloud"}:
            deployment = "local"
        self._deployment = deployment
        self._api_key = os.environ.get("OLLAMA_API_KEY", "").strip()

        default_base_url = (
            "https://ollama.com/v1" if self._deployment == "cloud" else "http://127.0.0.1:11434/v1"
        )
        # Accept OLLAMA_BASE_URL as either root (http://host:11434) or /v1 URL.
        raw_base_url = os.environ.get("OLLAMA_BASE_URL", default_base_url).strip()
        if not raw_base_url:
            raw_base_url = default_base_url
        raw_base_url = raw_base_url.rstrip("/")

        if raw_base_url.endswith("/v1"):
            self._ollama_root = raw_base_url[:-3]
            self.base_url = f"{raw_base_url}/"
        else:
            self._ollama_root = raw_base_url
            self.base_url = f"{raw_base_url}/v1/"

        parsed_root = urlparse(self._ollama_root)
        self._is_cloud = "ollama.com" in parsed_root.netloc.lower()
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        self._client = httpx.AsyncClient(
            base_url=self._ollama_root,
            timeout=httpx.Timeout(60.0),
            headers=headers,
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
            await self._client.aclose()
            logger.info("Ollama service cleanup completed")
        except Exception as e:
            logger.error(f"Error during Ollama service cleanup: {e}")

    def _is_cache_valid(self) -> bool:
        if self._cache_timestamp == 0:
            return False
        return time.time() - self._cache_timestamp < self._cache_ttl

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _build_messages_payload(request: ChatCompletionRequest) -> list[dict[str, str]]:
        return [{"role": msg.role.value, "content": msg.content} for msg in request.messages]

    def _build_chat_payload(
        self, request: ChatCompletionRequest, *, stream: bool
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": self._build_messages_payload(request),
            "stream": stream,
        }
        if request.max_tokens:
            # Ollama option equivalent of OpenAI max_tokens.
            payload["options"] = {"num_predict": request.max_tokens}
        return payload

    async def create_chat_completion(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        try:
            logger.info(f"Ollama chat completion with model: {request.model}")
            payload = self._build_chat_payload(request, stream=False)
            response = await self._client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

            message_data = data.get("message") or {}
            role_value = str(message_data.get("role") or MessageRole.ASSISTANT.value)
            try:
                role = MessageRole(role_value)
            except ValueError:
                role = MessageRole.ASSISTANT

            prompt_tokens = self._safe_int(data.get("prompt_eval_count"))
            completion_tokens = self._safe_int(data.get("eval_count"))

            return ChatCompletionResponse(
                id=f"chatcmpl-{uuid.uuid4().hex[:29]}",
                object="chat.completion",
                created=int(time.time()),
                model=str(data.get("model") or request.model),
                choices=[
                    ChatCompletionChoice(
                        index=0,
                        message=ChatMessage(
                            role=role, content=str(message_data.get("content") or "")
                        ),
                        finish_reason=str(data.get("done_reason") or "stop"),
                    )
                ],
                usage=ChatCompletionUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
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
            payload = self._build_chat_payload(request, stream=True)
            stream_id = f"chatcmpl-{uuid.uuid4().hex[:29]}"
            final_sent = False

            async with self._client.stream("POST", "/api/chat", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        logger.debug("Skipping non-JSON Ollama stream line: %s", line)
                        continue

                    message_data = data.get("message") or {}
                    content = message_data.get("content")
                    if content:
                        stream_response = ChatCompletionStreamResponse(
                            id=stream_id,
                            object="chat.completion.chunk",
                            created=int(time.time()),
                            model=str(data.get("model") or request.model),
                            choices=[
                                ChatCompletionStreamChoice(
                                    index=0,
                                    delta={
                                        "role": MessageRole.ASSISTANT.value,
                                        "content": str(content),
                                    },
                                    finish_reason=None,
                                )
                            ],
                        )
                        yield f"data: {stream_response.model_dump_json(exclude_none=True)}\n\n"

                    if data.get("done"):
                        stream_response = ChatCompletionStreamResponse(
                            id=stream_id,
                            object="chat.completion.chunk",
                            created=int(time.time()),
                            model=str(data.get("model") or request.model),
                            choices=[
                                ChatCompletionStreamChoice(
                                    index=0,
                                    delta={},
                                    finish_reason=str(data.get("done_reason") or "stop"),
                                )
                            ],
                        )
                        yield f"data: {stream_response.model_dump_json(exclude_none=True)}\n\n"
                        final_sent = True
                        break

            if not final_sent:
                stream_response = ChatCompletionStreamResponse(
                    id=stream_id,
                    object="chat.completion.chunk",
                    created=int(time.time()),
                    model=request.model,
                    choices=[
                        ChatCompletionStreamChoice(
                            index=0,
                            delta={},
                            finish_reason="stop",
                        )
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
        # Ollama does not directly support image generation in this backend.
        raise NotImplementedError(
            "Ollama does not natively support image generation. Use G4F for images."
        )

    async def get_models(self) -> list[ModelInfo]:
        if self._is_cache_valid() and self._models_cache:
            return self._models_cache
        try:
            logger.info("Fetching models from local Ollama")
            response = await self._client.get("/api/tags")
            response.raise_for_status()
            payload = response.json()

            result = []
            for model in payload.get("models", []):
                model_id = str(model.get("name") or "").strip()
                if not model_id:
                    continue
                result.append(
                    ModelInfo(
                        id=model_id,
                        created=int(time.time()),
                        owned_by="ollama",
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

    async def get_providers(self) -> list[ProviderInfo]:
        provider_id = "Cloud Ollama" if self._is_cloud else "Local Ollama"
        no_auth = (not self._is_cloud) or bool(self._api_key)
        return [
            ProviderInfo(
                id=provider_id,
                url=self.base_url,
                models=[m.id for m in (self._models_cache or [])],
                params={
                    "supports_stream": True,
                    "no_auth": no_auth,
                    "requires_api_key": self._is_cloud,
                    "logged_in": bool(self._api_key) if self._is_cloud else True,
                },
            )
        ]

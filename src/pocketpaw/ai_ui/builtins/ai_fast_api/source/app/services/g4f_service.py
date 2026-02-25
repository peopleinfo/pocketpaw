import inspect
import json
import time
import uuid
from typing import AsyncGenerator, List, Optional

from g4f.client import AsyncClient
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import settings
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
from ..utils.sanitizer import sanitize_response, sanitize_stream_chunk


class G4FService:
    """Service for handling G4F operations via the v7 AsyncClient API."""

    def __init__(self):
        self._models_cache: Optional[List[ModelInfo]] = None
        self._providers_cache: Optional[List[ProviderInfo]] = None
        self._cache_timestamp = 0
        self._cache_ttl = 300
        self._initialized = False
        self._client = AsyncClient()

    async def initialize(self):
        try:
            logger.info("Initializing G4F service...")
            await self.get_models()
            await self.get_providers()
            self._initialized = True
            logger.info("G4F service initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize G4F service: {e}")
            self._initialized = True

    async def cleanup(self):
        try:
            logger.info("Cleaning up G4F service...")
            self._models_cache = None
            self._providers_cache = None
            self._initialized = False
            logger.info("G4F service cleanup completed")
        except Exception as e:
            logger.error(f"Error during G4F service cleanup: {e}")

    def _is_cache_valid(self) -> bool:
        if self._cache_timestamp == 0:
            return False
        return time.time() - self._cache_timestamp < self._cache_ttl

    @retry(
        stop=stop_after_attempt(settings.g4f_retries),
        wait=wait_exponential(multiplier=1, min=4, max=10),
    )
    async def create_chat_completion(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        try:
            logger.info(f"Creating chat completion with model: {request.model}")
            messages = [
                {"role": msg.role.value, "content": msg.content}
                for msg in request.messages
            ]

            response = await self._client.chat.completions.create(
                model=request.model,
                messages=messages,
                stream=False,
                web_search=request.web_search,
            )

            completion_id = f"chatcmpl-{uuid.uuid4().hex[:29]}"
            raw_content = response.choices[0].message.content if response.choices else ""
            content = sanitize_response(raw_content)

            return ChatCompletionResponse(
                id=completion_id,
                object="chat.completion",
                created=int(time.time()),
                model=request.model,
                choices=[
                    ChatCompletionChoice(
                        index=0,
                        message=ChatMessage(
                            role=MessageRole.ASSISTANT, content=content
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=ChatCompletionUsage(
                    prompt_tokens=0, completion_tokens=0, total_tokens=0
                ),
            )
        except Exception as e:
            logger.error(f"Error in chat completion: {e}", exc_info=True)
            raise

    async def create_chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncGenerator[str, None]:
        try:
            logger.info(
                f"Creating streaming chat completion with model: {request.model}"
            )
            messages = [
                {"role": msg.role.value, "content": msg.content}
                for msg in request.messages
            ]
            completion_id = f"chatcmpl-{uuid.uuid4().hex[:29]}"

            stream_or_coro = self._client.chat.completions.create(
                model=request.model,
                messages=messages,
                stream=True,
                web_search=request.web_search,
            )
            stream = (
                (await stream_or_coro) if inspect.isawaitable(stream_or_coro) else stream_or_coro
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = sanitize_stream_chunk(chunk.choices[0].delta.content)
                    if not content:
                        continue
                    stream_response = ChatCompletionStreamResponse(
                        id=completion_id,
                        object="chat.completion.chunk",
                        created=int(time.time()),
                        model=request.model,
                        choices=[
                            ChatCompletionStreamChoice(
                                index=0,
                                delta={"role": "assistant", "content": content},
                                finish_reason=None,
                            )
                        ],
                    )
                    yield f"data: {stream_response.model_dump_json()}\n\n"

            final_response = ChatCompletionStreamResponse(
                id=completion_id,
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
            yield f"data: {final_response.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"Error in streaming chat completion: {e}")
            error_response = {
                "error": {
                    "message": str(e),
                    "type": "server_error",
                    "code": "internal_error",
                }
            }
            yield f"data: {json.dumps(error_response)}\n\n"

    @retry(
        stop=stop_after_attempt(settings.g4f_retries),
        wait=wait_exponential(multiplier=1, min=4, max=10),
    )
    async def create_image_generation(
        self, request: ImageGenerationRequest
    ) -> ImageGenerationResponse:
        try:
            logger.info(f"Creating image generation with model: {request.model}")
            response = await self._client.images.generate(
                model=request.model,
                prompt=request.prompt,
            )

            images = []
            for img in response.data:
                images.append(
                    ImageData(
                        url=getattr(img, "url", None),
                        b64_json=getattr(img, "b64_json", None),
                    )
                )

            return ImageGenerationResponse(
                created=int(time.time()),
                data=images if images else [ImageData(url=str(response))],
            )
        except Exception as e:
            logger.error(f"Error in image generation: {e}")
            raise

    async def get_models(self) -> List[ModelInfo]:
        if self._is_cache_valid() and self._models_cache:
            return self._models_cache
        try:
            logger.info("Fetching models from G4F")
            from g4f.models import ModelUtils

            now = int(time.time())
            models = [
                ModelInfo(id=name, created=now, owned_by="g4f")
                for name in sorted(ModelUtils.convert.keys())
            ]
            if not models:
                models = self._get_default_models()
            self._models_cache = models
            self._cache_timestamp = time.time()
            return models
        except Exception as e:
            logger.error(f"Error fetching models: {e}")
            return self._get_default_models()

    async def get_providers(self) -> List[ProviderInfo]:
        if self._is_cache_valid() and self._providers_cache:
            return self._providers_cache
        try:
            logger.info("Fetching G4F providers")
            providers_list = self._get_default_providers()
            self._providers_cache = providers_list
            self._cache_timestamp = time.time()
            logger.info(f"Retrieved {len(providers_list)} providers")
            return providers_list
        except Exception as e:
            logger.error(f"Error fetching providers: {e}")
            return self._get_default_providers()

    def _get_default_models(self) -> List[ModelInfo]:
        now = int(time.time())
        return [
            ModelInfo(id="gpt-4o", created=now, owned_by="g4f"),
            ModelInfo(id="gpt-4o-mini", created=now, owned_by="g4f"),
            ModelInfo(id="gpt-4", created=now, owned_by="g4f"),
            ModelInfo(id="gpt-3.5-turbo", created=now, owned_by="g4f"),
            ModelInfo(id="claude-3.5-sonnet", created=now, owned_by="g4f"),
            ModelInfo(id="gemini-pro", created=now, owned_by="g4f"),
            ModelInfo(id="llama-3.1-70b", created=now, owned_by="g4f"),
        ]

    def _get_default_providers(self) -> List[ProviderInfo]:
        return [
            ProviderInfo(
                id="Auto",
                url=None,
                models=["gpt-4o", "gpt-4o-mini", "gpt-4", "gpt-3.5-turbo"],
                params={"supports_stream": True},
            ),
            ProviderInfo(
                id="Bing",
                url="https://www.bing.com",
                models=["gpt-4", "gpt-4o"],
                params={"supports_stream": True},
            ),
            ProviderInfo(
                id="ChatGPT",
                url="https://chatgpt.com",
                models=["gpt-4o", "gpt-4o-mini"],
                params={"supports_stream": True},
            ),
        ]


g4f_service = G4FService()

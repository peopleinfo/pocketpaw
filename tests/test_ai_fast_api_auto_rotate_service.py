import time

import pytest

from pocketpaw.ai_ui.builtins.ai_fast_api.source.app.models import (
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
    ChatMessage,
    MessageRole,
    ProviderInfo,
)
from pocketpaw.ai_ui.builtins.ai_fast_api.source.app.services.auto_service import AutoRotateService


class _DummyService:
    def __init__(self, provider_params: dict, *, fail: bool = False, label: str = "dummy"):
        self._provider_params = provider_params
        self._fail = fail
        self._label = label
        self.chat_calls = 0

    async def initialize(self):
        return None

    async def cleanup(self):
        return None

    async def create_chat_completion(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        self.chat_calls += 1
        if self._fail:
            raise RuntimeError(f"{self._label} failed")
        return ChatCompletionResponse(
            id=f"chatcmpl-{self._label}",
            object="chat.completion",
            created=int(time.time()),
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role=MessageRole.ASSISTANT, content=f"ok-{self._label}"),
                    finish_reason="stop",
                )
            ],
            usage=ChatCompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )

    async def create_chat_completion_stream(self, request: ChatCompletionRequest):
        raise NotImplementedError

    async def create_image_generation(self, request):
        raise NotImplementedError

    async def get_models(self):
        return []

    async def get_providers(self):
        return [
            ProviderInfo(
                id=self._label,
                url=None,
                models=[],
                params=self._provider_params,
            )
        ]


@pytest.mark.asyncio
async def test_auto_rotate_skips_inactive_oauth_backends():
    svc = AutoRotateService()
    svc._backend_chain = ["codex", "g4f"]
    svc._max_rotate_retry = 4

    inactive_codex = _DummyService(
        {"supports_stream": True, "oauth": True, "logged_in": False, "no_auth": False},
        fail=True,
        label="codex",
    )
    active_g4f = _DummyService(
        {"supports_stream": True, "no_auth": True},
        fail=False,
        label="g4f",
    )
    svc._services = {
        "codex": inactive_codex,
        "g4f": active_g4f,
    }

    request = ChatCompletionRequest(
        model="gpt-4.1",
        messages=[ChatMessage(role=MessageRole.USER, content="hello")],
        stream=False,
    )

    response = await svc.create_chat_completion(request)
    assert response.choices[0].message.content == "ok-g4f"
    assert inactive_codex.chat_calls == 0
    assert active_g4f.chat_calls == 1


@pytest.mark.asyncio
async def test_auto_rotate_raises_when_no_active_backends():
    svc = AutoRotateService()
    svc._backend_chain = ["codex", "qwen"]
    svc._max_rotate_retry = 4
    svc._services = {
        "codex": _DummyService(
            {"supports_stream": True, "oauth": True, "logged_in": False, "no_auth": False},
            label="codex",
        ),
        "qwen": _DummyService(
            {"supports_stream": True, "oauth": True, "logged_in": False, "no_auth": False},
            label="qwen",
        ),
    }

    request = ChatCompletionRequest(
        model="gpt-4.1",
        messages=[ChatMessage(role=MessageRole.USER, content="hello")],
        stream=False,
    )

    with pytest.raises(RuntimeError, match="no active backends"):
        await svc.create_chat_completion(request)

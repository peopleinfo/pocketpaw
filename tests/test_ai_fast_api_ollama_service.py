import json

import httpx
import pytest

from pocketpaw.ai_ui.builtins.ai_fast_api.source.app.config import Settings
from pocketpaw.ai_ui.builtins.ai_fast_api.source.app.models import (
    ChatCompletionRequest,
    ChatMessage,
    MessageRole,
)
from pocketpaw.ai_ui.builtins.ai_fast_api.source.app.services.ollama_service import OllamaService


async def _build_service_with_transport(transport: httpx.MockTransport) -> OllamaService:
    service = OllamaService()
    await service._client.aclose()
    service._client = httpx.AsyncClient(transport=transport, base_url="http://test-ollama")
    return service


@pytest.mark.asyncio
async def test_get_models_uses_ollama_tags_endpoint():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/tags"
        return httpx.Response(
            status_code=200,
            json={
                "models": [
                    {"name": "llama3.1:8b"},
                    {"name": "qwen2.5:7b"},
                ]
            },
        )

    service = await _build_service_with_transport(httpx.MockTransport(handler))
    models = await service.get_models()
    await service.cleanup()

    assert [model.id for model in models] == ["llama3.1:8b", "qwen2.5:7b"]
    assert all(model.owned_by == "ollama" for model in models)


@pytest.mark.asyncio
async def test_create_chat_completion_uses_ollama_chat_endpoint():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["stream"] is False
        assert payload["options"]["num_predict"] == 64
        assert payload["messages"] == [{"role": "user", "content": "Ping"}]
        return httpx.Response(
            status_code=200,
            json={
                "model": "llama3.1:8b",
                "message": {"role": "assistant", "content": "Pong"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 11,
                "eval_count": 3,
            },
        )

    service = await _build_service_with_transport(httpx.MockTransport(handler))
    response = await service.create_chat_completion(
        ChatCompletionRequest(
            model="llama3.1:8b",
            messages=[ChatMessage(role=MessageRole.USER, content="Ping")],
            max_tokens=64,
            stream=False,
        )
    )
    await service.cleanup()

    assert response.model == "llama3.1:8b"
    assert response.choices[0].message.role == MessageRole.ASSISTANT
    assert response.choices[0].message.content == "Pong"
    assert response.usage is not None
    assert response.usage.prompt_tokens == 11
    assert response.usage.completion_tokens == 3
    assert response.usage.total_tokens == 14


@pytest.mark.asyncio
async def test_create_chat_completion_stream_parses_ndjson_and_emits_sse():
    captured_payload: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/chat"
        captured_payload.update(json.loads(request.content.decode("utf-8")))
        lines = [
            json.dumps(
                {
                    "model": "llama3.1:8b",
                    "message": {"role": "assistant", "content": "Hello"},
                    "done": False,
                }
            ),
            json.dumps(
                {
                    "model": "llama3.1:8b",
                    "message": {"role": "assistant", "content": " world"},
                    "done": False,
                }
            ),
            json.dumps(
                {
                    "model": "llama3.1:8b",
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "done_reason": "stop",
                }
            ),
        ]
        return httpx.Response(status_code=200, text="\n".join(lines) + "\n")

    service = await _build_service_with_transport(httpx.MockTransport(handler))
    request = ChatCompletionRequest(
        model="llama3.1:8b",
        messages=[ChatMessage(role=MessageRole.USER, content="Ping")],
        stream=True,
    )
    chunks = [chunk async for chunk in service.create_chat_completion_stream(request)]
    await service.cleanup()

    assert captured_payload["stream"] is True
    assert chunks[-1] == "data: [DONE]\n\n"

    events = [json.loads(chunk[6:].strip()) for chunk in chunks if chunk != "data: [DONE]\n\n"]
    assert events[0]["choices"][0]["delta"]["content"] == "Hello"
    assert events[1]["choices"][0]["delta"]["content"] == " world"
    assert events[-1]["choices"][0]["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_cloud_deployment_uses_cloud_defaults_and_api_key(monkeypatch):
    monkeypatch.setenv("OLLAMA_DEPLOYMENT", "cloud")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")

    service = OllamaService()
    providers = await service.get_providers()
    await service.cleanup()

    assert service.base_url == "https://ollama.com/v1/"
    assert service._client.headers.get("Authorization") == "Bearer test-key"
    assert providers[0].id == "Cloud Ollama"
    assert providers[0].params["requires_api_key"] is True
    assert providers[0].params["logged_in"] is True
    assert providers[0].params["no_auth"] is True


@pytest.mark.asyncio
async def test_cloud_deployment_without_key_is_not_no_auth(monkeypatch):
    monkeypatch.setenv("OLLAMA_DEPLOYMENT", "cloud")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)

    service = OllamaService()
    providers = await service.get_providers()
    await service.cleanup()

    assert providers[0].id == "Cloud Ollama"
    assert providers[0].params["requires_api_key"] is True
    assert providers[0].params["logged_in"] is False
    assert providers[0].params["no_auth"] is False


def test_settings_resolves_local_ollama_model_from_split_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_DEPLOYMENT", "local")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("OLLAMA_LOCAL_MODEL", "llama3.2:3b")
    monkeypatch.setenv("OLLAMA_CLOUD_MODEL", "llama3.3:70b")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)

    settings = Settings()

    assert settings.ollama_deployment == "local"
    assert settings.ollama_local_model == "llama3.2:3b"
    assert settings.ollama_cloud_model == "llama3.3:70b"
    assert settings.ollama_model == "llama3.2:3b"
    assert settings.ollama_base_url == "http://127.0.0.1:11434/v1"


def test_settings_infers_cloud_deployment_and_uses_cloud_model(monkeypatch):
    monkeypatch.setenv("OLLAMA_DEPLOYMENT", "unknown")
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://ollama.com/v1")
    monkeypatch.setenv("OLLAMA_LOCAL_MODEL", "llama3.2:3b")
    monkeypatch.setenv("OLLAMA_CLOUD_MODEL", "llama3.3:70b")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)

    settings = Settings()

    assert settings.ollama_deployment == "cloud"
    assert settings.ollama_model == "llama3.3:70b"
    assert settings.ollama_base_url == "https://ollama.com/v1"

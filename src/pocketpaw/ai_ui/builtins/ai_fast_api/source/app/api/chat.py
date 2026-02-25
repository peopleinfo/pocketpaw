from typing import Union

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ErrorResponse,
)
from ..services import get_service
from ..utils.logger import logger
from ..utils.sanitizer import sanitize_input


router = APIRouter(prefix="/v1", tags=["Chat Completions"])

IMAGE_MODEL_IDS = frozenset({
    "flux", "flux-pro", "flux-dev", "flux-schnell",
    "dall-e-3", "dall-e-2", "gpt-image", "sdxl-turbo",
    "sd-3.5-large", "midjourney",
})


def _sanitize_request(request: ChatCompletionRequest) -> ChatCompletionRequest:
    for msg in request.messages:
        if msg.role.value in ("user", "system"):
            msg.content = sanitize_input(msg.content)
    return request


@router.post(
    "/chat/completions",
    response_model=Union[ChatCompletionResponse, ErrorResponse],
    summary="Create chat completion",
    description=(
        "Creates a model response for the given chat conversation. "
        "Compatible with OpenAI API."
    ),
)
async def create_chat_completion(
    request: ChatCompletionRequest,
) -> Union[ChatCompletionResponse, StreamingResponse]:
    try:
        if not request.messages:
            raise HTTPException(status_code=400, detail="Messages cannot be empty")

        request = _sanitize_request(request)
        svc = get_service()

        logger.info(
            f"Chat completion request: model={request.model}, "
            f"messages={len(request.messages)}, stream={request.stream}, "
            f"provider={request.provider}"
        )

        if request.stream:
            return StreamingResponse(
                svc.create_chat_completion_stream(request),
                media_type="text/plain",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Content-Type": "text/event-stream",
                },
            )
        else:
            response = await svc.create_chat_completion(request)
            logger.info(f"Chat completion successful: {response.id}")
            return response

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error in chat completion: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in chat completion: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error occurred while processing chat completion",
        )


@router.get(
    "/chat/completions/models",
    summary="List chat models",
    description="List available models for chat completions",
)
async def list_chat_models():
    try:
        svc = get_service()
        models = await svc.get_models()
        chat_models = [m for m in models if m.id not in IMAGE_MODEL_IDS]
        return {"object": "list", "data": chat_models}
    except Exception as e:
        logger.error(f"Error listing chat models: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve chat models")

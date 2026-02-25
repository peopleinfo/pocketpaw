from typing import Union

from fastapi import APIRouter, HTTPException

from ..models import (
    ErrorResponse,
    ImageGenerationRequest,
    ImageGenerationResponse,
    ModelInfo,
)
from ..services import get_service
from ..utils.logger import logger

router = APIRouter(prefix="/v1", tags=["Images"])

IMAGE_MODEL_IDS = frozenset({
    "flux", "flux-pro", "flux-dev", "flux-schnell",
    "dall-e-3", "dall-e-2", "gpt-image", "sdxl-turbo",
    "sd-3.5-large", "midjourney",
})


@router.post(
    "/images/generate",
    response_model=Union[ImageGenerationResponse, ErrorResponse],
    summary="Generate images",
    description="Creates an image given a text prompt. Compatible with OpenAI API.",
)
async def create_image_generation(
    request: ImageGenerationRequest,
) -> ImageGenerationResponse:
    try:
        if not request.prompt or not request.prompt.strip():
            raise HTTPException(status_code=400, detail="Prompt cannot be empty")

        if request.response_format not in ("url", "b64_json"):
            raise HTTPException(
                status_code=400,
                detail="Response format must be 'url' or 'b64_json'",
            )

        valid_sizes = ["256x256", "512x512", "1024x1024", "1792x1024", "1024x1792"]
        if request.size not in valid_sizes:
            logger.warning(f"Non-standard size requested: {request.size}")

        logger.info(
            f"Image generation request: model={request.model}, "
            f"prompt='{request.prompt[:50]}...', "
            f"size={request.size}, format={request.response_format}, "
            f"provider={request.provider}"
        )

        svc = get_service()
        response = await svc.create_image_generation(request)
        logger.info(f"Image generation successful: {len(response.data)} image(s)")
        return response

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error in image generation: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in image generation: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error occurred while generating image",
        )


@router.get(
    "/images/models",
    summary="List image models",
    description="List available models for image generation",
)
async def list_image_models():
    try:
        svc = get_service()
        models = await svc.get_models()
        image_models = [m for m in models if m.id in IMAGE_MODEL_IDS]

        if not image_models:
            import time as _time

            created = int(_time.time())
            image_models = [
                ModelInfo(id=name, created=created, owned_by="g4f")
                for name in ["flux", "flux-pro", "dall-e-3", "gpt-image"]
            ]

        return {"object": "list", "data": image_models}
    except Exception as e:
        logger.error(f"Error listing image models: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve image models")

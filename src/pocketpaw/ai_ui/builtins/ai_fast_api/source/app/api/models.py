from typing import Union

from fastapi import APIRouter, HTTPException

from ..models import (
    ErrorResponse,
    ModelInfo,
    ModelsResponse,
    ProvidersResponse,
)
from ..services import get_service
from ..utils.logger import logger

router = APIRouter(prefix="/v1", tags=["Models & Providers"])


@router.get(
    "/models",
    response_model=Union[ModelsResponse, ErrorResponse],
    summary="List models",
    description="Lists the currently available models. Compatible with OpenAI API.",
)
async def list_models() -> ModelsResponse:
    try:
        logger.info("Fetching available models")
        svc = get_service()
        models = await svc.get_models()
        response = ModelsResponse(data=models)
        logger.info(f"Retrieved {len(models)} models")
        return response
    except Exception as e:
        logger.error(f"Error listing models: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve models")


@router.get(
    "/models/{model_id}",
    response_model=Union[ModelInfo, ErrorResponse],
    summary="Retrieve model",
    description="Retrieves a model instance. Compatible with OpenAI API.",
)
async def retrieve_model(model_id: str) -> ModelInfo:
    try:
        logger.info(f"Fetching model: {model_id}")
        svc = get_service()
        models = await svc.get_models()
        for model in models:
            if model.id == model_id:
                return model
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving model {model_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve model '{model_id}'"
        )


@router.get(
    "/providers",
    response_model=Union[ProvidersResponse, ErrorResponse],
    summary="List providers",
    description="Lists the currently available providers.",
)
async def list_providers() -> ProvidersResponse:
    try:
        logger.info("Fetching available providers")
        svc = get_service()
        providers = await svc.get_providers()
        response = ProvidersResponse(data=providers)
        logger.info(f"Retrieved {len(providers)} providers")
        return response
    except Exception as e:
        logger.error(f"Error listing providers: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve providers")


@router.get(
    "/providers/{provider_id}",
    summary="Retrieve provider",
    description="Retrieves detailed information about a specific provider.",
)
async def retrieve_provider(provider_id: str) -> dict:
    try:
        logger.info(f"Fetching provider: {provider_id}")
        svc = get_service()
        providers = await svc.get_providers()
        for provider in providers:
            if provider.id == provider_id:
                return {
                    "id": provider.id,
                    "url": provider.url,
                    "models": provider.models,
                    "params": provider.params,
                    "object": "provider",
                }
        raise HTTPException(
            status_code=404, detail=f"Provider '{provider_id}' not found"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving provider {provider_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve provider '{provider_id}'",
        )

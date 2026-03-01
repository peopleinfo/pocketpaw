import time
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from .. import __version__
from ..config import settings
from ..models import HealthResponse
from ..utils.logger import logger

router = APIRouter(tags=["Health & Status"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Check the health status of the API server",
)
async def health_check() -> HealthResponse:
    try:
        return HealthResponse(status="healthy", version=__version__, timestamp=int(time.time()))
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unavailable")


@router.get(
    "/status",
    summary="Detailed status",
    description="Get detailed status information about the API server",
)
async def status_check() -> Dict[str, Any]:
    try:
        return {
            "status": "operational",
            "version": __version__,
            "timestamp": int(time.time()),
            "config": {
                "debug": settings.debug,
                "host": settings.host,
                "port": settings.port,
                "llm_backend": settings.llm_backend,
                "rate_limit": {
                    "requests": settings.rate_limit_requests,
                    "window": settings.rate_limit_window,
                },
            },
            "features": {
                "chat_completions": True,
                "image_generation": True,
                "streaming": True,
                "web_search": True,
                "provider_selection": True,
            },
            "endpoints": {
                "chat": "/v1/chat/completions",
                "images": "/v1/images/generate",
                "models": "/v1/models",
                "providers": "/v1/providers",
                "health": "/health",
                "docs": "/docs",
            },
        }
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unavailable")


@router.get(
    "/",
    summary="API information",
    description="Get basic API information and available endpoints",
)
async def root() -> Dict[str, Any]:
    return {
        "name": settings.api_title,
        "description": settings.api_description,
        "version": __version__,
        "llm_backend": settings.llm_backend,
        "docs_url": "/docs",
        "openapi_url": "/openapi.json",
        "endpoints": {
            "chat_completions": "/v1/chat/completions",
            "image_generation": "/v1/images/generate",
            "models": "/v1/models",
            "providers": "/v1/providers",
            "health": "/health",
            "status": "/status",
        },
        "features": [
            "OpenAI-compatible API",
            "Pluggable LLM backends (Auto Rotate, G4F, Ollama, Codex OAuth, Qwen OAuth, Gemini OAuth)",
            "Streaming responses",
            "Image generation",
            "Web search integration",
            "Rate limiting",
            "Request logging",
            "Response sanitization",
        ],
        "compatibility": "OpenAI API v1",
    }

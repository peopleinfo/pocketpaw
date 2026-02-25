from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from .config import settings
from .services import get_service
from .utils.logger import logger
from .utils.middleware import ErrorHandlingMiddleware, LoggingMiddleware
from .api import chat, images, models, health
from . import __version__


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.api_title} v{__version__}")
    logger.info(f"LLM backend: {settings.llm_backend}")
    try:
        svc = get_service()
        await svc.initialize()
        logger.info("LLM service initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize LLM service: {e}")
    yield
    logger.info(f"Shutting down {settings.api_title}")
    try:
        svc = get_service()
        await svc.cleanup()
    except Exception as e:
        logger.error(f"Error during service cleanup: {e}")


app = FastAPI(
    title=settings.api_title,
    description=settings.api_description,
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

if settings.cors_enabled:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info(f"CORS enabled with origins: {settings.cors_origins}")

app.add_middleware(ErrorHandlingMiddleware)
app.add_middleware(LoggingMiddleware)

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(images.router)
app.include_router(models.router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "message": "Internal server error",
                "type": "internal_error",
                "code": "internal_error",
            }
        },
    )


def create_app() -> FastAPI:
    return app


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
        access_log=True,
    )

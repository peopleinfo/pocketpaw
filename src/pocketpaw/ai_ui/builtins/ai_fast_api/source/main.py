#!/usr/bin/env python3
"""Main entry point for the AI FastAPI server."""

import uvicorn
from app.main import create_app
from app.config import settings
from app.utils.logger import logger


def main():
    """Main function to run the FastAPI server."""
    try:
        app = create_app()

        logger.info(f"Starting {settings.api_title} server...")
        logger.info(f"  Host: {settings.host}")
        logger.info(f"  Port: {settings.port}")
        logger.info(f"  Debug: {settings.debug}")
        logger.info(f"  LLM Backend: {settings.llm_backend}")
        if settings.llm_backend.lower() == "g4f":
            logger.info(f"  G4F Provider: {settings.g4f_provider}")
            logger.info(f"  G4F Model: {settings.g4f_model}")
        elif settings.llm_backend.lower() == "codex":
            logger.info(f"  Codex Model: {settings.codex_model}")
        logger.info(
            f"  Rate Limit: {settings.rate_limit_requests} req/{settings.rate_limit_window}s"
        )

        uvicorn.run(
            "app.main:create_app",
            host=settings.host,
            port=settings.port,
            log_level="info" if not settings.debug else "debug",
            reload=settings.debug,
            factory=True,
        )

    except KeyboardInterrupt:
        logger.info("Server shutdown requested by user")
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        raise


if __name__ == "__main__":
    main()

import os
from typing import Dict, List

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self):
        self.host: str = os.getenv("HOST", "0.0.0.0")
        self.port: int = int(os.getenv("PORT", "8000"))
        self.debug: bool = os.getenv("DEBUG", "false").lower() == "true"

        self.api_title: str = os.getenv("API_TITLE", "AI FastAPI Server")
        self.api_description: str = os.getenv(
            "API_DESCRIPTION",
            "OpenAI-compatible API with pluggable LLM backends (G4F, Ollama, etc.)",
        )
        self.api_version: str = os.getenv("API_VERSION", "2.0.0")

        self.llm_backend: str = os.getenv("LLM_BACKEND", "g4f")

        self.g4f_provider: str = os.getenv("G4F_PROVIDER", "auto")
        self.g4f_model: str = os.getenv("G4F_MODEL", "gpt-4o-mini")
        self.g4f_timeout: int = int(os.getenv("G4F_TIMEOUT", "60"))
        self.g4f_retries: int = int(os.getenv("G4F_RETRIES", "3"))

        self.rate_limit_requests: int = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))
        self.rate_limit_window: int = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

        self.cors_enabled: bool = os.getenv("CORS_ENABLED", "true").lower() == "true"
        cors_origins_str = os.getenv("CORS_ORIGINS", "*")
        self.cors_origins: List[str] = [
            origin.strip() for origin in cors_origins_str.split(",")
        ]

        self.openai_api_base: str = os.getenv("OPENAI_API_BASE", "/v1")

        # Sanitizer: defaults secure; set to false to disable
        self.sanitizer_redact_input: bool = (
            os.getenv("SANITIZER_REDACT_INPUT", "true").lower() == "true"
        )
        self.sanitizer_exclude_domains: str = os.getenv("SANITIZER_EXCLUDE_DOMAINS", "")
        self.sanitizer_exclude_phrases: str = os.getenv("SANITIZER_EXCLUDE_PHRASES", "")


settings = Settings()

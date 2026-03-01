import os

from dotenv import load_dotenv

load_dotenv()


def _infer_ollama_deployment(raw_deployment: str, raw_base_url: str) -> str:
    deployment = (raw_deployment or "").strip().lower()
    if deployment in {"local", "cloud"}:
        return deployment
    return "cloud" if "ollama.com" in (raw_base_url or "").strip().lower() else "local"


def _resolve_ollama_model(
    deployment: str,
    local_model: str,
    cloud_model: str,
    legacy_model: str,
) -> str:
    fallback = legacy_model or "llama3.1"
    if deployment == "cloud":
        return cloud_model or fallback
    return local_model or fallback


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
        raw_ollama_deployment = os.getenv("OLLAMA_DEPLOYMENT", "local")
        raw_ollama_base_url = os.getenv("OLLAMA_BASE_URL", "").strip()
        self.ollama_deployment: str = _infer_ollama_deployment(
            raw_ollama_deployment,
            raw_ollama_base_url,
        )
        default_ollama_base_url = (
            "https://ollama.com/v1"
            if self.ollama_deployment == "cloud"
            else "http://127.0.0.1:11434/v1"
        )
        self.ollama_base_url: str = raw_ollama_base_url or default_ollama_base_url
        legacy_ollama_model = os.getenv("OLLAMA_MODEL", "").strip()
        self.ollama_local_model: str = (
            os.getenv("OLLAMA_LOCAL_MODEL", "").strip() or legacy_ollama_model or "llama3.1"
        )
        self.ollama_cloud_model: str = (
            os.getenv("OLLAMA_CLOUD_MODEL", "").strip() or legacy_ollama_model or "llama3.1"
        )
        # Backward-compatible effective model used by existing call sites.
        self.ollama_model: str = _resolve_ollama_model(
            self.ollama_deployment,
            self.ollama_local_model,
            self.ollama_cloud_model,
            legacy_ollama_model,
        )
        self.ollama_api_key: str = os.getenv("OLLAMA_API_KEY", "")
        self.g4f_timeout: int = int(os.getenv("G4F_TIMEOUT", "60"))
        self.g4f_retries: int = int(os.getenv("G4F_RETRIES", "3"))
        self.codex_model: str = os.getenv("CODEX_MODEL", "gpt-5")
        self.codex_timeout: int = int(os.getenv("CODEX_TIMEOUT", "90"))
        self.codex_bin: str = os.getenv("CODEX_BIN", "")
        self.qwen_model: str = os.getenv("QWEN_MODEL", "qwen3-coder-plus")
        self.qwen_timeout: int = int(os.getenv("QWEN_TIMEOUT", "90"))
        self.qwen_bin: str = os.getenv("QWEN_BIN", "")
        self.gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.gemini_timeout: int = int(os.getenv("GEMINI_TIMEOUT", "90"))
        self.gemini_bin: str = os.getenv("GEMINI_BIN", "")
        self.auto_max_rotate_retry: int = int(os.getenv("AUTO_MAX_ROTATE_RETRY", "4"))
        self.auto_rotate_backends: str = os.getenv(
            "AUTO_ROTATE_BACKENDS", "g4f,ollama,codex,qwen,gemini"
        )
        self.auto_g4f_model: str = os.getenv("AUTO_G4F_MODEL", "gpt-4o-mini")
        self.auto_ollama_model: str = os.getenv("AUTO_OLLAMA_MODEL", "llama3.1")
        self.auto_codex_model: str = os.getenv("AUTO_CODEX_MODEL", "gpt-5")
        self.auto_qwen_model: str = os.getenv("AUTO_QWEN_MODEL", "qwen3-coder-plus")
        self.auto_gemini_model: str = os.getenv("AUTO_GEMINI_MODEL", "gemini-2.5-flash")

        self.rate_limit_requests: int = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))
        self.rate_limit_window: int = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

        self.cors_enabled: bool = os.getenv("CORS_ENABLED", "true").lower() == "true"
        cors_origins_str = os.getenv("CORS_ORIGINS", "*")
        self.cors_origins: list[str] = [origin.strip() for origin in cors_origins_str.split(",")]

        self.openai_api_base: str = os.getenv("OPENAI_API_BASE", "/v1")

        # Sanitizer: defaults secure; set to false to disable
        self.sanitizer_redact_input: bool = (
            os.getenv("SANITIZER_REDACT_INPUT", "true").lower() == "true"
        )
        self.sanitizer_exclude_domains: str = os.getenv("SANITIZER_EXCLUDE_DOMAINS", "")
        self.sanitizer_exclude_phrases: str = os.getenv("SANITIZER_EXCLUDE_PHRASES", "")


settings = Settings()

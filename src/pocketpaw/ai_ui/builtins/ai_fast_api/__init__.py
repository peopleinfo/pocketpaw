"""Built-in: AI Fast API — OpenAI-compatible server powered by G4F.

The full upstream source from https://github.com/next-dev-team/ai-fast-api
is bundled in the ``source/`` directory so the plugin works offline and can
be freely customised.  No git clone is needed at install time.
"""

from pathlib import Path

from pocketpaw.ai_ui.builtins._base import BuiltinDefinition

_SOURCE_DIR = Path(__file__).resolve().parent / "source"

_MANIFEST = {
    "name": "AI Fast API",
    "description": (
        "OpenAI-compatible API with pluggable LLM backends "
        "(G4F, Ollama, Codex OAuth, Qwen OAuth, Gemini OAuth). "
        "Chat completions, image generation, streaming — "
        "all through a unified local endpoint."
    ),
    "icon": "zap",
    "version": "2.0.0",
    "start": "bash start.sh",
    "install": "bash install.sh",
    "requires": ["uv", "python"],
    "port": 8000,
    "web_view": "native",
    "web_view_path": "/",
    "env": {
        "HOST": "0.0.0.0",
        "PORT": "8000",
        "DEBUG": "true",
        "LLM_BACKEND": "g4f",
        "G4F_PROVIDER": "auto",
        "G4F_MODEL": "gpt-4o-mini",
        "CODEX_MODEL": "gpt-5",
        "QWEN_MODEL": "qwen3-coder-plus",
        "GEMINI_MODEL": "gemini-2.5-flash",
    },
    "openapi": "openapi.json",
}

DEFINITION: BuiltinDefinition = {
    "id": "ai-fast-api",
    "manifest": _MANIFEST,
    "source_dir": str(_SOURCE_DIR),
    "files": {},
    "gallery": {
        "id": "ai-fast-api",
        "name": "AI Fast API",
        "description": (
            "OpenAI-compatible API with pluggable backends "
            "(G4F, Ollama, Codex OAuth, Qwen OAuth, Gemini OAuth). "
            "Chat, images, streaming — zero API keys needed."
        ),
        "icon": "zap",
        "source": "builtin:ai-fast-api",
        "stars": "G4F / Multi-Provider",
        "category": "Curated / Built-in",
    },
}

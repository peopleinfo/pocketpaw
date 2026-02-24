"""Built-in: AI Fast API — OpenAI-compatible server powered by G4F.

This is a git-cloned builtin: the repo at
https://github.com/next-dev-team/ai-fast-api is cloned and overlaid
with a ``pocketpaw.json`` manifest so it works as a first-class plugin.
"""

from pocketpaw.ai_ui.builtins._base import BuiltinDefinition

_MANIFEST = {
    "name": "AI Fast API",
    "description": (
        "OpenAI-compatible API server powered by GPT4Free (G4F). "
        "Chat completions, image generation, multiple AI providers — "
        "all through a unified local endpoint."
    ),
    "icon": "zap",
    "version": "1.0.0",
    "start": "bash start.sh",
    "install": "bash install.sh",
    "requires": ["uv", "python"],
    "port": 8000,
    "env": {
        "HOST": "0.0.0.0",
        "PORT": "8000",
        "DEBUG": "true",
        "G4F_PROVIDER": "auto",
        "G4F_MODEL": "gpt-4o-mini",
    },
    "openapi": "openapi.json",
}

_INSTALL_SH = """\
#!/bin/bash
set -e

echo "Setting up AI Fast API..."

if ! command -v uv &> /dev/null; then
    echo "Installing uv package manager..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source "$HOME/.local/bin/env" 2>/dev/null || true
fi

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    uv venv .venv
fi

echo "Installing dependencies..."
. .venv/bin/activate 2>/dev/null || source .venv/Scripts/activate 2>/dev/null
uv pip install -r requirements.txt

echo "AI Fast API installed successfully!"
"""

_START_SH = """\
#!/bin/bash
set -e

VENV_PATHS=(".venv/bin/activate" ".venv/Scripts/activate")
for path in "${VENV_PATHS[@]}"; do
    if [ -f "$path" ]; then
        source "$path"
        break
    fi
done

echo "Starting AI Fast API on port ${PORT:-8000}..."
python main.py
"""

_OPENAPI_JSON = """\
{
  "openapi": "3.0.3",
  "info": {
    "title": "AI Fast API — G4F OpenAI-Compatible Server",
    "version": "1.0.0",
    "description": "OpenAI-compatible REST API powered by GPT4Free."
  },
  "servers": [
    {
      "url": "http://localhost:8000",
      "description": "Local AI Fast API server"
    }
  ],
  "paths": {
    "/v1/chat/completions": {
      "post": {
        "summary": "Chat Completion",
        "description": "Create a chat completion (streaming and non-streaming).",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "model": {"type": "string", "example": "gpt-4o-mini"},
                  "messages": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "role": {"type": "string", "example": "user"},
                        "content": {"type": "string", "example": "Hello!"}
                      }
                    }
                  },
                  "temperature": {"type": "number", "example": 0.7},
                  "max_tokens": {"type": "integer", "example": 150},
                  "stream": {"type": "boolean", "example": false}
                }
              }
            }
          }
        },
        "responses": {
          "200": { "description": "Successful chat completion." }
        }
      }
    },
    "/v1/models": {
      "get": {
        "summary": "List Models",
        "description": "List all available AI models.",
        "responses": {
          "200": { "description": "A list of available models." }
        }
      }
    },
    "/v1/images/generations": {
      "post": {
        "summary": "Generate Image",
        "description": "Generate images from a text prompt.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "prompt": {"type": "string", "example": "A sunset over mountains"},
                  "model": {"type": "string", "example": "dall-e-3"},
                  "n": {"type": "integer", "example": 1},
                  "size": {"type": "string", "example": "1024x1024"}
                }
              }
            }
          }
        },
        "responses": {
          "200": { "description": "Generated image URLs." }
        }
      }
    },
    "/health": {
      "get": {
        "summary": "Health Check",
        "description": "Check server health status.",
        "responses": {
          "200": { "description": "Server is healthy." }
        }
      }
    }
  }
}"""

DEFINITION: BuiltinDefinition = {
    "id": "ai-fast-api",
    "manifest": _MANIFEST,
    "git_source": "https://github.com/next-dev-team/ai-fast-api.git",
    "files": {
        "install.sh": _INSTALL_SH,
        "start.sh": _START_SH,
        "openapi.json": _OPENAPI_JSON,
    },
    "gallery": {
        "id": "ai-fast-api",
        "name": "AI Fast API",
        "description": (
            "OpenAI-compatible API server powered by GPT4Free. "
            "Chat, images, multiple providers — zero API keys needed."
        ),
        "icon": "zap",
        "source": "builtin:ai-fast-api",
        "stars": "G4F / Multi-Provider",
        "category": "Curated / Built-in",
    },
}

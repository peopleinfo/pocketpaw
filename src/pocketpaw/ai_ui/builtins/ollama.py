"""Built-in: Ollama — run open-source LLMs locally."""

from pocketpaw.ai_ui.builtins._base import BuiltinDefinition

_MANIFEST = {
    "name": "Ollama",
    "description": (
        "Run open-source LLMs locally — Llama, Mistral, Phi, and more. "
        "Self-contained 1-click install."
    ),
    "icon": "brain",
    "version": "1.0.0",
    "start": "bash start.sh",
    "install": "uv run python install.py",
    "requires": ["uv"],
    "port": 11434,
    "openapi": "openapi.json",
}

_START_SH = """\
#!/bin/bash
export OLLAMA_ORIGINS="*"

# Start Ollama's local server in the background
./ollama serve &
SERVER_PID=$!

sleep 2

# Pull a tiny demo model in the background
./ollama pull qwen2.5:0.5b &

echo "Ollama is running on port 11434 (demo model is fetching in background)"
wait $SERVER_PID
"""

_INSTALL_PY = """\
import urllib.request
import zipfile
import shutil
import os
import platform
import stat

def install_ollama():
    os_name = platform.system().lower()
    machine = platform.machine().lower()

    print(f"Downloading Ollama for {os_name} {machine}...")
    headers = {"User-Agent": "Mozilla/5.0"}

    if os_name == "darwin":
        url = "https://ollama.com/download/Ollama-darwin.zip"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response, open("ollama.zip", "wb") as out_file:
            shutil.copyfileobj(response, out_file)
        print("Extracting...")
        with zipfile.ZipFile("ollama.zip", "r") as z:
            z.extract("Ollama.app/Contents/Resources/ollama")
        shutil.move("Ollama.app/Contents/Resources/ollama", "ollama")
        shutil.rmtree("Ollama.app")
        os.remove("ollama.zip")
    elif os_name == "linux":
        arch = "amd64" if machine in ("x86_64", "amd64") else "arm64"
        url = f"https://ollama.com/download/ollama-linux-{arch}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response, open("ollama", "wb") as out_file:
            shutil.copyfileobj(response, out_file)
    else:
        url = "https://ollama.com/download/ollama-windows-amd64.zip"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response, open("ollama.zip", "wb") as out_file:
            shutil.copyfileobj(response, out_file)
        with zipfile.ZipFile("ollama.zip", "r") as z:
            z.extract("ollama.exe")
        os.remove("ollama.zip")

    if os.path.exists("ollama"):
        st = os.stat("ollama")
        os.chmod("ollama", st.st_mode | stat.S_IEXEC)

    print("Ollama downloaded successfully!")

if __name__ == "__main__":
    install_ollama()
"""

_OPENAPI_JSON = """\
{
  "openapi": "3.0.3",
  "info": {
    "title": "Ollama Local REST API",
    "version": "1.0.0",
    "description": "Generated API specification for the local Ollama instance."
  },
  "servers": [
    {
      "url": "http://localhost:11434",
      "description": "Local Ollama server"
    }
  ],
  "paths": {
    "/api/tags": {
      "get": {
        "summary": "List Models",
        "description": "List models that are available locally.",
        "responses": {
          "200": { "description": "A list of models." }
        }
      }
    },
    "/api/generate": {
      "post": {
        "summary": "Generate a completion",
        "description": "Generate a response for a given prompt with a provided model.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "model": {"type": "string", "example": "qwen2.5:0.5b"},
                  "prompt": {"type": "string", "example": "Why is the sky blue?"},
                  "stream": {"type": "boolean", "example": false}
                }
              }
            }
          }
        },
        "responses": {
          "200": { "description": "Successful generation." }
        }
      }
    },
    "/api/chat": {
      "post": {
        "summary": "Generate a chat completion",
        "description": "Generate the next message in a chat with a provided model.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "model": {"type": "string", "example": "qwen2.5:0.5b"},
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
    }
  }
}"""

DEFINITION: BuiltinDefinition = {
    "id": "ollama",
    "manifest": _MANIFEST,
    "files": {
        "start.sh": _START_SH,
        "install.py": _INSTALL_PY,
        "openapi.json": _OPENAPI_JSON,
    },
    "gallery": {
        "id": "ollama",
        "name": "Ollama (Built-in)",
        "description": (
            "Run open-source LLMs locally — Llama, Mistral, Phi, and more. "
            "Self-contained 1-click install."
        ),
        "icon": "brain",
        "source": "builtin:ollama",
        "stars": "Native Wrapper",
        "category": "Curated / Built-in",
    },
}

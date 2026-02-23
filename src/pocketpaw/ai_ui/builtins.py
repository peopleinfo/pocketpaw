import asyncio
import json
import shutil
from pathlib import Path

OLLAMA_MANIFEST = {
    "name": "Ollama",
    "description": "Run open-source LLMs locally — Llama, Mistral, Phi, and more. Self-contained 1-click install.",
    "icon": "brain",
    "version": "1.0.0",
    "start": "bash start.sh",
    "install": "uv run python install.py",
    "requires": ["uv"],
    "port": 11434,
    "openapi": "openapi.json"
}

OLLAMA_START_SH = '''#!/bin/bash
export OLLAMA_ORIGINS="*"

# 1. Start Ollama's local server in the background
./ollama serve &
SERVER_PID=$!

# Wait for the API socket to initialize
sleep 2

# 2. Trigger pulling a tiny demo model (qwen2.5:0.5b) in the background 
./ollama pull qwen2.5:0.5b &

# 3. Wait on the server process so PocketPaw tracks it as 'running'
echo "Ollama is running on port 11434 (demo model is fetching in background)"
wait $SERVER_PID
'''

OLLAMA_INSTALL_PY = '''import urllib.request
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
        # Windows
        url = "https://ollama.com/download/ollama-windows-amd64.zip"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response, open("ollama.zip", "wb") as out_file:
            shutil.copyfileobj(response, out_file)
        with zipfile.ZipFile("ollama.zip", "r") as z:
            z.extract("ollama.exe")
        os.remove("ollama.zip")

    # Make executable
    if os.path.exists("ollama"):
        st = os.stat("ollama")
        os.chmod("ollama", st.st_mode | stat.S_IEXEC)
    
    print("Ollama downloaded successfully!")

if __name__ == "__main__":
    install_ollama()
'''

OLLAMA_OPENAPI_JSON = '''{
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
          "200": {
            "description": "A list of models."
          }
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
          "200": {
            "description": "Successful generation."
          }
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
          "200": {
            "description": "Successful chat completion."
          }
        }
      }
    }
  }
}'''

BUILTINS = {
    "ollama": {
        "manifest": OLLAMA_MANIFEST,
        "files": {
            "start.sh": OLLAMA_START_SH,
            "install.py": OLLAMA_INSTALL_PY,
            "openapi.json": OLLAMA_OPENAPI_JSON
        }
    }
}

async def install_builtin(app_id: str, plugins_dir: Path) -> dict:
    if app_id not in BUILTINS:
        raise ValueError(f"Unknown built-in app: {app_id}")
        
    app_def = BUILTINS[app_id]
    plugin_id = app_id
    
    dest = plugins_dir / plugin_id
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    
    # Write manifest
    (dest / "pocketpaw.json").write_text(json.dumps(app_def["manifest"], indent=2), encoding="utf-8")
    
    # Write files
    for filename, content in app_def["files"].items():
        (dest / filename).write_text(content, encoding="utf-8")
        
    # Run install command if present
    install_cmd = app_def["manifest"].get("install")
    if install_cmd:
        proc = await asyncio.create_subprocess_shell(
            f"cd {dest} && {install_cmd}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr_out = await asyncio.wait_for(proc.communicate(), timeout=300)
        
        if proc.returncode != 0:
            err = stderr_out.decode(errors="replace").strip()
            raise RuntimeError(f"Failed to setup builtin {app_id} app: {err}")
            
    return {"status": "ok", "message": f"{app_def['manifest']['name']} has been added!", "plugin_id": plugin_id}

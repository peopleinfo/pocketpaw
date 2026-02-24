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

echo "Installing dependencies into isolated .venv..."
# --python ensures uv installs into this plugin's venv, not the host.
# Shared UV_CACHE_DIR (set by PocketPaw) means identical wheels are
# hardlinked — no duplicate downloads, no wasted disk.
uv pip install --python .venv/bin/python -r requirements.txt

echo "Generating OpenAPI spec from FastAPI routes..."
.venv/bin/python -c "
from app.main import create_app
import json
app = create_app()
spec = app.openapi()
with open('openapi.json', 'w') as f:
    json.dump(spec, f, indent=2)
print(f'  Generated openapi.json ({len(spec.get(\"paths\", {}))} endpoints)')
"

echo "AI Fast API installed successfully!"

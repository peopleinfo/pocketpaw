#!/bin/bash
set -euo pipefail

if [ ! -d ".venv" ]; then
  uv venv .venv
fi

uv pip install --python .venv/bin/python -U "g4f[gui]"

echo "g4f GUI dependencies installed."

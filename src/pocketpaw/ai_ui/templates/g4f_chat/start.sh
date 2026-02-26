#!/bin/bash
set -euo pipefail

if [ ! -x ".venv/bin/python" ]; then
  echo "Missing .venv/bin/python. Install this plugin first." >&2
  exit 1
fi

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"

exec .venv/bin/python -m g4f.cli gui --host "$HOST" --port "$PORT"

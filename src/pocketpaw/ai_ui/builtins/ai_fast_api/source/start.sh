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

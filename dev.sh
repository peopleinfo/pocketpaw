#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

lsof -ti :8888 | xargs kill -9 2>/dev/null || true

uv run pocketpaw --dev

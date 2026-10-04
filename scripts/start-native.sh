#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/src"
# File-backed state requires one worker so per-player request locks cover every request.
exec .venv/bin/python -m uvicorn openbachelors.app:app --host 127.0.0.1 --port 18443 --workers 1

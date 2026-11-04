#!/usr/bin/env bash
# Start the backend (http://localhost:8000) and the web app (http://localhost:5173). Ctrl+C stops both.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
[ -d "$ROOT/.tools" ] && export PATH="$(ls -d "$ROOT"/.tools/node-*/bin 2>/dev/null | head -1):$PATH"
[ -x "$ROOT/backend/.venv/bin/uvicorn" ] || { echo "Run ./setup.sh first."; exit 1; }

"$ROOT/backend/.venv/bin/uvicorn" app.main:app --app-dir "$ROOT/backend" --port 8000 &
BACK=$!
trap 'kill $BACK 2>/dev/null' EXIT
echo "Invoice Desk → http://localhost:5173"
cd "$ROOT/frontend" && npx vite --port 5173

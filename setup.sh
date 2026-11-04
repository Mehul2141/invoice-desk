#!/usr/bin/env bash
# One-time setup: installs backend (Python) and frontend (Node) dependencies and creates backend/.env.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
[ -d "$ROOT/.tools" ] && export PATH="$(ls -d "$ROOT"/.tools/node-*/bin 2>/dev/null | head -1):$PATH"

command -v python3 >/dev/null || { echo "Python 3.9+ is required (python3 not found)."; exit 1; }
command -v npm >/dev/null || { echo "Node.js 18+ is required (npm not found) — https://nodejs.org"; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || { echo "Python 3.9+ is required."; exit 1; }

echo "→ Installing backend dependencies"
[ -d "$ROOT/backend/.venv" ] || python3 -m venv "$ROOT/backend/.venv"
"$ROOT/backend/.venv/bin/pip" install -q --upgrade pip
"$ROOT/backend/.venv/bin/pip" install -q -r "$ROOT/backend/requirements.txt"

echo "→ Installing frontend dependencies"
(cd "$ROOT/frontend" && npm install --silent)

if [ ! -f "$ROOT/backend/.env" ]; then
  cp "$ROOT/backend/.env.example" "$ROOT/backend/.env"
  echo "→ Created backend/.env — add your GEMINI_API_KEY (or ANTHROPIC_API_KEY) there."
fi
echo "Done. Start the app with ./start.sh and open http://localhost:5173"

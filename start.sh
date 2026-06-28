#!/bin/bash
# Start Chess Review.
#
# Default: PRODUCTION mode — builds the frontend (only when sources changed)
# and serves everything from one uvicorn process on :8000. This is much
# snappier than dev mode (minified bundle, no StrictMode double-render).
#
#   ./start.sh          production (recommended)
#   ./start.sh --dev    development (vite HMR on :5173 + uvicorn on :8000)
#
# Press Ctrl+C or close the terminal to stop.

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ ! -d "venv" ]; then
  echo "Missing venv. Run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

if [ ! -d "frontend/node_modules" ]; then
  echo "Missing frontend deps. Run: cd frontend && npm install"
  exit 1
fi

source venv/bin/activate

if [ "$1" = "--dev" ]; then
  cleanup() {
    echo ""
    echo "Stopping Chess Review…"
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    exit 0
  }
  trap cleanup EXIT INT TERM

  echo "Starting backend  → http://localhost:8000"
  uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
  BACKEND_PID=$!

  sleep 1

  echo "Starting frontend → http://localhost:5173 (dev mode, HMR)"
  (cd frontend && npm run dev -- --host 127.0.0.1) &
  FRONTEND_PID=$!

  echo ""
  echo "Chess Review is running in DEV mode."
  echo "  Open: http://localhost:5173"
  echo "  Stop: Ctrl+C or close this terminal window"
  echo ""

  wait
  exit 0
fi

# --- production mode ---

# Rebuild only when a source file is newer than the last build.
needs_build=0
if [ ! -f "frontend/dist/index.html" ]; then
  needs_build=1
elif [ -n "$(find frontend/src frontend/index.html frontend/vite.config.js css -newer frontend/dist/index.html -print -quit 2>/dev/null)" ]; then
  needs_build=1
fi

if [ "$needs_build" = "1" ]; then
  echo "Building frontend (sources changed)…"
  (cd frontend && npm run build)
fi

echo ""
echo "Chess Review is running."
echo "  Open: http://localhost:8000"
echo "  Stop: Ctrl+C or close this terminal window"
echo ""

CHESS_REVIEW_DESKTOP=1 exec uvicorn backend.main:app --host 127.0.0.1 --port 8000

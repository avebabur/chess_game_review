#!/bin/bash
# Stop Chess Review servers
#
# Also kills any orphaned Stockfish processes. When uvicorn is killed via
# SIGTERM mid-analysis, python-chess doesn't always propagate the quit to
# its Stockfish subprocess — the engine becomes a zombie consuming a CPU
# core silently. This explicit cleanup makes restarts truly clean.

kill $(lsof -ti :8000) 2>/dev/null && echo "Stopped backend on port 8000"
kill $(lsof -ti :5173) 2>/dev/null && echo "Stopped frontend on port 5173"
pkill -f "/opt/homebrew/bin/stockfish" 2>/dev/null && echo "Stopped orphaned Stockfish"
echo "Done."

#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/logs"

# Clear any existing processes first
"$ROOT/scripts/stop.sh"
sleep 1

# Start FastAPI backend
echo "Starting backend..."
cd "$ROOT"
uv run uvicorn api.main:app --port 8000 > "$ROOT/logs/backend.log" 2>&1 &
echo $! > "$ROOT/.backend.pid"
echo "Backend running on http://localhost:8000 (logs: logs/backend.log)"

# Start Next.js frontend
echo "Starting frontend..."
cd "$ROOT/web"
npm run dev > "$ROOT/logs/frontend.log" 2>&1 &
echo $! > "$ROOT/.frontend.pid"
echo "Frontend running on http://localhost:3000 (logs: logs/frontend.log)"

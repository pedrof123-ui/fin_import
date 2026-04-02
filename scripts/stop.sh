#!/usr/bin/env bash

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

kill_port() {
    local port="$1"
    local pids
    pids=$(lsof -ti tcp:"$port" 2>/dev/null)
    if [ -n "$pids" ]; then
        echo "Stopping processes on port $port (PIDs: $pids)"
        kill $pids 2>/dev/null || true
    fi
}

kill_port 8000
kill_port 3000

rm -f "$ROOT/.backend.pid" "$ROOT/.frontend.pid"
echo "Done."

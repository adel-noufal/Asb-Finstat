#!/usr/bin/env bash
# Starts ASB Finstat locally on mac/linux: FastAPI backend on :8000 + Vite frontend on :5173.
# Safe to re-run - already-running parts are skipped.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python="$root/backend/.venv/bin/python"
if [ ! -x "$python" ]; then
    echo "Backend venv missing. Run: cd backend; python3 -m venv .venv; .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi
if [ ! -d "$root/frontend/node_modules" ]; then
    echo "Frontend deps missing. Run: cd frontend; npm install" >&2
    exit 1
fi
if [ ! -f "$root/backend/.env" ]; then
    echo "WARNING: backend/.env not found - copy backend/.env.example and set OPENROUTER_API_KEY, AI calls will fail without it." >&2
fi

port_busy() {
    nc -z localhost "$1" >/dev/null 2>&1
}

mkdir -p "$root/logs"

if port_busy 8000; then
    echo "Backend already listening on :8000 - skipping"
else
    (cd "$root/backend" && nohup "$python" -m uvicorn app.main:app --reload --port 8000 >"$root/logs/backend.log" 2>&1 &
     echo "Backend starting (pid $!), logging to logs/backend.log")
fi

if port_busy 5173; then
    echo "Frontend already listening on :5173 - skipping"
else
    (cd "$root/frontend" && nohup npm run dev >"$root/logs/frontend.log" 2>&1 &
     echo "Frontend starting (pid $!), logging to logs/frontend.log")
fi

deadline=$(( $(date +%s) + 30 ))
while [ "$(date +%s)" -lt "$deadline" ] && ! (port_busy 8000 && port_busy 5173); do
    sleep 0.5
done

port_busy 8000 || echo "WARNING: Backend did not come up on :8000 - check logs/backend.log" >&2
port_busy 5173 || echo "WARNING: Frontend did not come up on :5173 - check logs/frontend.log" >&2

echo ""
echo "Backend  : http://localhost:8000"
echo "Frontend : http://localhost:5173  <- open this"

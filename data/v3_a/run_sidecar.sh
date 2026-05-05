#!/usr/bin/env bash
# Start the v3-A FastAPI sidecar that Trafficure proxies to.
# Default port 8001 (override with V3A_PORT). Run from the repo root.
set -euo pipefail

PORT="${V3A_PORT:-8001}"
HOST="${V3A_HOST:-0.0.0.0}"

echo "Starting v3-A sidecar on http://${HOST}:${PORT}"
echo "Trafficure should set V3A_SIDECAR_URL=http://localhost:${PORT}"
exec python3 -m uvicorn data.v3_a.server:app --host "${HOST}" --port "${PORT}" --reload

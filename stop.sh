#!/bin/bash
# Stops all AI Observability test services started by start.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SCRIPT_DIR}/.oneagent.pid"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Dynatrace AI Observability — stopping all services"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── OneAgent app (native) ─────────────────────────────────────────────────────
if [ -f "${PID_FILE}" ]; then
    PID=$(cat "${PID_FILE}")
    if kill -0 "${PID}" 2>/dev/null; then
        echo "  Stopping OneAgent app (PID ${PID})..."
        kill "${PID}"
    else
        echo "  OneAgent app already stopped."
    fi
    rm -f "${PID_FILE}"
else
    echo "  OneAgent app not running (no PID file)."
fi

# ── SDK containers ────────────────────────────────────────────────────────────
echo "  Stopping containers..."
cd "${SCRIPT_DIR}"
podman-compose down 2>/dev/null || true

echo ""
echo "  All services stopped."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

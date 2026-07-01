#!/bin/bash
# Starts all three AI Observability test services:
#   - app_oneagent.py  runs natively on the host (port 8001) so host OneAgent can instrument it
#   - openllmetry, openinference, otel-collector run via podman-compose (ports 8002/8003)
#
# Usage:
#   ./start.sh        — start everything
#   ./start.sh --build — rebuild containers before starting (use after code changes)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SCRIPT_DIR}/.oneagent.pid"
LOG_FILE="${SCRIPT_DIR}/.oneagent.log"
VENV_DIR="${SCRIPT_DIR}/.venv-oneagent"
BUILD_FLAG=""
[ "${1:-}" = "--build" ] && BUILD_FLAG="--build"

# ── Validate .env ─────────────────────────────────────────────────────────────
if [ ! -f "${SCRIPT_DIR}/.env" ]; then
    echo ""
    echo "  ERROR: .env not found."
    echo "  Copy .env.template to .env and fill in your credentials, then retry."
    echo ""
    exit 1
fi

# Load env vars into this shell so native uvicorn picks them up
set -a
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/.env"
set +a

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Dynatrace AI Observability — starting all services"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── OneAgent app (native) ─────────────────────────────────────────────────────
echo ""
echo "  [1/2] OneAgent app — running natively on port 8001"

# Stop any already-running instance
if [ -f "${PID_FILE}" ]; then
    OLD_PID=$(cat "${PID_FILE}")
    if kill -0 "${OLD_PID}" 2>/dev/null; then
        echo "        Stopping previous instance (PID ${OLD_PID})..."
        kill "${OLD_PID}" && sleep 1
    fi
    rm -f "${PID_FILE}"
fi

# Create virtualenv if needed
if [ ! -d "${VENV_DIR}" ]; then
    echo "        Creating virtual environment..."
    python3 -m venv "${VENV_DIR}"
fi

# Install/update requirements
echo "        Installing requirements..."
"${VENV_DIR}/bin/pip" install -q --upgrade pip
"${VENV_DIR}/bin/pip" install -q -r "${SCRIPT_DIR}/requirements_oneagent.txt"

# Start natively (cd first so uvicorn can find app_oneagent module)
cd "${SCRIPT_DIR}"
"${VENV_DIR}/bin/uvicorn" app_oneagent:app \
    --host 0.0.0.0 \
    --port 8001 \
    > "${LOG_FILE}" 2>&1 &

echo $! > "${PID_FILE}"
echo "        Started (PID $(cat "${PID_FILE}")) — logs: .oneagent.log"
echo "        OneAgent on this host will instrument this process automatically."

# ── SDK services via podman-compose ──────────────────────────────────────────
echo ""
echo "  [2/2] OpenLLMetry + OpenInference + OTel Collector — via podman-compose"
echo ""

cd "${SCRIPT_DIR}"
# Start only the SDK services — oneagent runs natively above
# shellcheck disable=SC2086
podman-compose up -d ${BUILD_FLAG} openllmetry openinference otel-collector

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  All services running:"
echo ""
echo "    OneAgent      http://localhost:8001/ask  (native — host OneAgent instrumented)"
echo "    OpenLLMetry   http://localhost:8002/ask  (container)"
echo "    OpenInference http://localhost:8003/ask  (container)"
echo ""
echo "  Run tests:  ./test_all.sh"
echo "  Stop all:   ./stop.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

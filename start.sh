#!/bin/bash
# Starts all three AI Observability test services via podman-compose:
#   - app_oneagent.py      (port 8001) — host OneAgent instruments via code-module injection
#   - app_openllmetry.py   (port 8002) — traceloop-sdk → OTLP → Dynatrace
#   - app_openinference.py (port 8003) — openinference → OTel Collector → Dynatrace
#
# Usage:
#   ./start.sh        — start everything
#   ./start.sh --build — rebuild containers before starting (use after code changes)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Dynatrace AI Observability — starting all services"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── OneAgent preload library permission check ─────────────────────────────────
# On some Linux distributions (e.g. Fedora 44), the OneAgent installer sets
# liboneagentproc.so without an execute bit, causing the preload to be silently
# skipped. Detect and fix this automatically.
PRELOAD_LIB="/lib64/liboneagentproc.so"
if [ ! -f "${PRELOAD_LIB}" ]; then
    PRELOAD_LIB="/usr/lib64/liboneagentproc.so"
fi
if [ -f "${PRELOAD_LIB}" ] && [ ! -x "${PRELOAD_LIB}" ]; then
    echo ""
    echo "  ⚠️  OneAgent preload library missing execute bit — fixing with sudo..."
    sudo chmod 755 "${PRELOAD_LIB}"
    echo "     Fixed: ${PRELOAD_LIB}"
fi

# ── All services via podman-compose ──────────────────────────────────────────
echo ""
echo "  Starting all services via podman-compose..."
echo ""

cd "${SCRIPT_DIR}"
# shellcheck disable=SC2086
podman-compose up -d ${BUILD_FLAG}

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  All services running:"
echo ""
echo "    OneAgent      http://localhost:8001/ask  (container — host OneAgent instrumented)"
echo "    OpenLLMetry   http://localhost:8002/ask  (container)"
echo "    OpenInference http://localhost:8003/ask  (container)"
echo ""
echo "  Run tests:  ./test_all.sh"
echo "  Stop all:   ./stop.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

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

# ── Detect OneAgent host library ──────────────────────────────────────────────
# OneAgent requires host-level files that only exist on Linux hosts with OneAgent
# installed. Detect the library once; skip the service gracefully if absent
# (e.g. on macOS dev machines). On some Linux distros (e.g. Fedora 44) the
# installer omits the execute bit — fix it automatically when found.
ONEAGENT_LIB=""
for candidate in /lib64/liboneagentproc.so /usr/lib64/liboneagentproc.so; do
    if [ -f "${candidate}" ]; then
        ONEAGENT_LIB="${candidate}"
        break
    fi
done

ONEAGENT_AVAILABLE=false
if [ -n "${ONEAGENT_LIB}" ]; then
    ONEAGENT_AVAILABLE=true
    if [ ! -x "${ONEAGENT_LIB}" ]; then
        echo ""
        echo "  ⚠️  OneAgent preload library missing execute bit — fixing with sudo..."
        sudo chmod 755 "${ONEAGENT_LIB}"
        echo "     Fixed: ${ONEAGENT_LIB}"
    fi
fi

# ── All services via podman-compose ──────────────────────────────────────────
echo ""
if [ "${ONEAGENT_AVAILABLE}" = "true" ]; then
    echo "  Starting all services via podman-compose..."
    echo ""
    cd "${SCRIPT_DIR}"
    # shellcheck disable=SC2086
    podman-compose up -d ${BUILD_FLAG}
else
    echo "  NOTE: OneAgent host library not found — skipping OneAgent service."
    echo "        Install Dynatrace OneAgent on this host to enable it."
    echo ""
    echo "  Starting remaining services via podman-compose..."
    echo ""
    cd "${SCRIPT_DIR}"
    # shellcheck disable=SC2086
    podman-compose up -d ${BUILD_FLAG} openllmetry openinference otel-collector mcp
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Services running:"
echo ""
if [ "${ONEAGENT_AVAILABLE}" = "true" ]; then
    echo "    OneAgent      http://localhost:8001/ask  (host OneAgent instrumented)"
fi
echo "    OpenLLMetry   http://localhost:8002/ask"
echo "    OpenInference http://localhost:8003/ask"
echo "    MCP           http://localhost:8004/ask"
echo ""
echo "  Run tests:  ./test_all.sh"
echo "  Stop all:   ./stop.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

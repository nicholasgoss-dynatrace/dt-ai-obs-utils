#!/bin/bash
# Entrypoint for the OneAgent container.
#
# NOTE: OneAgent 1.341+ blocks in-container installation by policy.
# Instrumentation for this service requires OneAgent to be installed on the HOST
# machine, where it automatically monitors all processes including those inside
# containers. See README for details.
#
# This entrypoint simply starts the app. If OneAgent is present on the host,
# it will instrument the Python process automatically.

set -e

echo "[OneAgent] Starting app (host-level OneAgent provides instrumentation)..."
echo "[OneAgent] If you see no data in Dynatrace, verify:"
echo "[OneAgent]   1. OneAgent is installed on the host machine"
echo "[OneAgent]   2. Python Anthropic sensor is enabled (Settings > OneAgent features)"
echo "[OneAgent]   3. Python FastAPI sensor is enabled (same location)"

exec uvicorn app_oneagent:app --host 0.0.0.0 --port 8000

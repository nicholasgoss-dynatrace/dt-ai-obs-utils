#!/bin/bash
# Entrypoint for the OneAgent container.
# Downloads and installs Dynatrace OneAgent at startup, then launches the app.
#
# Required env vars:
#   DT_ENDPOINT    — your Dynatrace tenant URL (e.g. https://abc12345.live.dynatrace.com)
#   DT_PAAS_TOKEN  — PaaS token from Settings > Integration > Platform as a Service
#
# Optional env vars:
#   DT_CONNECTION_POINT — override the connection endpoint (default: auto-detected)

set -e

if [ -n "$DT_PAAS_TOKEN" ] && [ -n "$DT_ENDPOINT" ]; then
    echo "[OneAgent] Downloading installer from ${DT_ENDPOINT}..."
    wget -q -O /tmp/oneagent.sh \
        "${DT_ENDPOINT}/api/v1/deployment/installer/agent/unix/default/latest?flavor=default&include=python&bitness=all" \
        --header="Authorization: Api-Token ${DT_PAAS_TOKEN}"

    echo "[OneAgent] Installing..."
    sh /tmp/oneagent.sh \
        --set-app-log-content-access=true \
        --set-infra-only=false \
        --set-host-group=dt-ai-obs-test
    rm /tmp/oneagent.sh

    echo "[OneAgent] Installation complete. Starting app..."
else
    echo "[OneAgent] WARNING: DT_PAAS_TOKEN or DT_ENDPOINT not set."
    echo "[OneAgent] OneAgent will NOT be installed — spans will not appear in AI Observability."
    echo "[OneAgent] Add DT_PAAS_TOKEN to your .env file and rebuild to enable instrumentation."
fi

exec uvicorn app_oneagent:app --host 0.0.0.0 --port 8000

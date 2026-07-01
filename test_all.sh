#!/bin/bash
# Send a test prompt to all three instrumentation variants simultaneously
# and print side-by-side results.
#
# Usage:
#   ./test_all.sh
#   ./test_all.sh "Your custom prompt here"
#
# Requires: podman-compose up (all services healthy)

PROMPT="${1:-What is observability, and why does it matter for AI systems?}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  DT AI Observability — Instrumentation comparison test"
echo "  Prompt: \"$PROMPT\""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

PAYLOAD=$(printf '{"prompt": "%s"}' "$PROMPT")

call_service() {
    local name="$1"
    local port="$2"
    local url="http://localhost:${port}/ask"

    echo ""
    echo "── $name (port $port) ──"
    response=$(curl -s -X POST "$url" \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD" \
        --max-time 30 2>&1)

    if [ $? -ne 0 ] || [ -z "$response" ]; then
        echo "  ERROR: no response (is the service running?)"
        return
    fi

    # Print formatted response
    echo "$response" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f\"  Model : {d.get('model', 'n/a')}\")
    print(f\"  Tokens: in={d.get('input_tokens', '?')} out={d.get('output_tokens', '?')}\")
    print(f\"  Result: {d.get('result', '')[:200]}\")
except:
    print(sys.stdin.read())
" 2>/dev/null || echo "$response"
}

# Fire all three requests in parallel, wait for all to finish
call_service "OneAgent"      8001 &
call_service "OpenLLMetry"   8002 &
call_service "OpenInference"  8003 &
wait

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Check AI Observability > Explorer in your Dynatrace tenant"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

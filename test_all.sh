#!/bin/bash
# Runs a curated set of prompts — ranging from poor to excellent quality —
# through all three instrumentation services simultaneously.
#
# The prompt variety gives Dynatrace AI Observability enough signal to
# surface patterns: which prompts produce high token costs, long latency,
# or low-quality responses.
#
# Usage:
#   ./test_all.sh              — run all 9 prompts
#   ./test_all.sh "my prompt"  — run a single custom prompt
#
# Requires: podman-compose up (all services healthy)

set -euo pipefail

# ── Prompt definitions ────────────────────────────────────────────────────────
# Parallel arrays: PROMPT_LABELS and PROMPTS must stay in sync.
# Tiers: POOR | MEDIOCRE | EXCELLENT

PROMPT_LABELS=(
    # Poor — vague, missing context, unanswerable without guessing
    "[POOR]      No context or subject"
    "[POOR]      No specificity"
    "[POOR]      Missing all detail"
    # Mediocre — some intent, but too broad or unstructured
    "[MEDIOCRE]  Common but overly broad"
    "[MEDIOCRE]  Reasonable topic, no constraints"
    "[MEDIOCRE]  Relevant but underspecified"
    # Excellent — specific role/context, structured ask, actionable output
    "[EXCELLENT] Structured comparison with scope"
    "[EXCELLENT] Debugging scenario with technical detail"
    "[EXCELLENT] Role + context + constraints + format"
)

PROMPTS=(
    # Poor
    "tell me stuff"
    "explain it"
    "fix my code"
    # Mediocre
    "What is observability?"
    "How does AI monitoring work?"
    "What should I look at when my service is slow?"
    # Excellent
    "Compare OpenTelemetry auto-instrumentation versus SDK-based manual instrumentation for monitoring Anthropic Claude API calls. Focus on setup complexity, attribute coverage, and suitability for a Python FastAPI service in a production environment."
    "Our Python service calls the Anthropic Claude API and we are seeing p99 latency spikes above 4 seconds. We use claude-haiku-4-5. Given distributed trace data showing HTTP entry spans and child LLM spans, walk me through a step-by-step approach to determine whether the bottleneck is prompt token volume, model cold-start, or network overhead."
    "You are an observability architect. I am instrumenting a Python FastAPI application that uses the Anthropic Claude API for a customer-facing chatbot processing 5,000 requests per day. Define the minimum set of gen_ai.* span attributes I must capture to answer these three questions in Dynatrace: (1) What is my daily token cost per model? (2) Which prompts produce the longest responses? (3) Are there error patterns tied to specific system prompt versions?"
)

# ── Helpers ───────────────────────────────────────────────────────────────────

# Build a safe JSON payload using Python to handle special characters
make_payload() {
    python3 -c "import json,sys; print(json.dumps({'prompt': sys.argv[1]}))" "$1"
}

make_error_payload() {
    python3 -c "import json,sys; print(json.dumps({'prompt': sys.argv[1], 'model': sys.argv[2]}))" "$1" "$2"
}

make_tool_payload() {
    python3 -c "import json,sys; print(json.dumps({'prompt': sys.argv[1], 'use_tools': True}))" "$1"
}

make_mcp_payload() {
    python3 -c "import json,sys; print(json.dumps({'prompt': sys.argv[1], 'use_mcp': True}))" "$1"
}

call_service() {
    local name="$1"
    local port="$2"
    local payload="$3"
    local expect_error="${4:-false}"

    local response
    response=$(curl -s -X POST "http://localhost:${port}/ask" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        --max-time 45 2>&1)

    if [ -z "$response" ]; then
        printf "    %-14s  ERROR — no response (is the service up?)\n" "$name"
        return
    fi

    python3 - "$name" "$expect_error" "$response" <<'PYEOF'
import sys, json

name         = sys.argv[1]
expect_error = sys.argv[2] == "true"
raw          = sys.argv[3]

try:
    d = json.loads(raw)
    if expect_error:
        detail = d.get("detail", raw)
        print(f"    {name:<14}  [EXPECTED ERROR] {str(detail)[:120]}")
    else:
        tokens_in  = d.get("input_tokens", "?")
        tokens_out = d.get("output_tokens", "?")
        model      = d.get("model", "n/a")
        snippet    = d.get("result", "")[:120].replace("\n", " ")
        print(f"    {name:<14}  [{model}] in={tokens_in} out={tokens_out}  \"{snippet}...\"")
except Exception:
    prefix = "[EXPECTED ERROR]" if expect_error else "PARSE ERROR"
    print(f"    {name:<14}  {prefix}: {raw[:120]}")
PYEOF
}

run_tool_round() {
    local prompt="What is 1234 * 5678 + 999?"
    local payload
    payload=$(make_tool_payload "$prompt")

    echo ""
    printf "  ── Tool-use round ───────────────────────────────────────────────────────\n"
    echo ""
    echo "  [TOOL USE]  Arithmetic prompt to invoke the calculator tool"
    printf "  Prompt: \"%s\"\n" "${prompt:0:90}"

    call_service "OneAgent"      8001 "$payload" &
    call_service "OpenLLMetry"   8002 "$payload" &
    call_service "OpenInference" 8003 "$payload" &
    wait
    echo ""
    echo "  Verify in Dynatrace: LLM spans should carry gen_ai.tool.name and tool call events."
}

run_mcp_round() {
    local prompt="What are the currently active problems in this Dynatrace environment? Summarize briefly."
    local mcp_payload plain_payload
    mcp_payload=$(make_mcp_payload "$prompt")
    plain_payload=$(make_payload "$prompt")

    echo ""
    printf "  ── MCP round ────────────────────────────────────────────────────────────\n"
    echo ""
    echo "  [MCP]       Dynatrace tools invoked via MCP stdio transport"
    printf "  Prompt: \"%s\"\n" "${prompt:0:90}"

    # Services 1-3 use use_mcp=true; service 4 (port 8004) always uses MCP internally
    call_service "OneAgent"      8001 "$mcp_payload" &
    call_service "OpenLLMetry"   8002 "$mcp_payload" &
    call_service "OpenInference" 8003 "$mcp_payload" &
    call_service "MCP"           8004 "$plain_payload" &
    wait
    echo ""
    echo "  Verify in Dynatrace: spans should carry mcp.tool.name and mcp.server.name attributes."
}

run_error_round() {
    local invalid_model="claude-not-a-real-model"
    local payload
    payload=$(make_error_payload "ping" "$invalid_model")

    echo ""
    printf "  ── Error validation round ───────────────────────────────────────────────\n"
    echo ""
    echo "  [ERROR]     Deliberate invalid model to verify error.type attribute capture"
    printf "  Model:  \"%s\"\n" "$invalid_model"

    call_service "OneAgent"      8001 "$payload" true &
    call_service "OpenLLMetry"   8002 "$payload" true &
    call_service "OpenInference" 8003 "$payload" true &
    wait
    echo ""
    echo "  Verify in Dynatrace: error spans should carry error.type on the LLM child span."
}

run_prompt() {
    local label="$1"
    local prompt="$2"
    local payload
    payload=$(make_payload "$prompt")

    echo ""
    echo "  $label"
    printf "  Prompt: \"%s\"\n" "${prompt:0:90}$([ ${#prompt} -gt 90 ] && echo '...')"

    call_service "OneAgent"     8001 "$payload" &
    call_service "OpenLLMetry"  8002 "$payload" &
    call_service "OpenInference" 8003 "$payload" &
    wait
}

# ── Main ──────────────────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Dynatrace AI Observability — Prompt quality stress test"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ $# -gt 0 ]; then
    # Single custom prompt passed as argument
    run_prompt "[CUSTOM]" "$1"
else
    # Run all prompts in sequence
    total=${#PROMPTS[@]}
    for i in "${!PROMPTS[@]}"; do
        echo ""
        printf "  ── Round %d/%d ──────────────────────────────────────────────────────────\n" \
            "$((i+1))" "$total"
        run_prompt "${PROMPT_LABELS[$i]}" "${PROMPTS[$i]}"

        # Brief pause between rounds so traces are clearly separated in Dynatrace
        if [ $((i+1)) -lt $total ]; then
            sleep 2
        fi
    done

    sleep 2
    run_tool_round

    sleep 2
    run_mcp_round

    sleep 2
    run_error_round
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Done. Check AI Observability → Explorer in your Dynatrace tenant."
echo "  Look for token count and latency differences across prompt quality tiers."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

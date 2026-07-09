"""
Dynatrace AI Observability — OpenLLMetry instrumentation test
=============================================================
Uses the traceloop-sdk to auto-instrument the LLM SDK and export
spans + metrics directly to Dynatrace via OTLP.

@workflow  — top-level trace entry (like a "request")
@task      — a named step inside the workflow

LLM provider is set via LLM_PROVIDER env var (default: anthropic).
Supported: anthropic, openai. The traceloop-sdk auto-instruments
whichever SDK is active — no code changes needed when switching providers.

Run locally:
    pip install -r requirements_openllmetry.txt
    uvicorn app_openllmetry:app --host 0.0.0.0 --port 8000

Run via podman-compose:
    podman-compose up openllmetry    # http://localhost:8002/ask

Test:
    curl -s -X POST http://localhost:8002/ask \
        -H "Content-Type: application/json" \
        -d '{"prompt": "What is observability?"}' | python3 -m json.tool

Prerequisites in .env:
    DT_ENDPOINT      — e.g. https://abc12345.live.dynatrace.com
    DT_API_TOKEN     — scopes: openTelemetryTrace.ingest, metrics.ingest, logs.ingest
    LLM_PROVIDER     — anthropic (default) or openai
    ANTHROPIC_API_KEY / OPENAI_API_KEY
    MODEL            — optional; defaults per provider if unset
"""

import os
import uuid

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from opentelemetry import trace
from pydantic import BaseModel
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from traceloop.sdk import Traceloop
from traceloop.sdk.decorators import task, workflow

import llm_client
import mcp_client
import log_setup

load_dotenv()

# Required so Dynatrace receives delta metrics (not cumulative)
os.environ["OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE"] = "delta"

DT_ENDPOINT = os.environ["DT_ENDPOINT"].rstrip("/")
DT_API_TOKEN = os.environ["DT_API_TOKEN"]
MODEL = llm_client.default_model()
SERVICE_NAME = os.getenv("SERVICE_NAME", "dt-ai-obs-openllmetry")

Traceloop.init(
    app_name=SERVICE_NAME,
    api_endpoint=f"{DT_ENDPOINT}/api/v2/otlp",
    headers={"Authorization": f"Api-Token {DT_API_TOKEN}"},
    disable_batch=True,
)

logger = log_setup.setup_logging(SERVICE_NAME, DT_ENDPOINT, DT_API_TOKEN)
client = llm_client.create_client()
app = FastAPI(title="DT AI Obs — OpenLLMetry test")
FastAPIInstrumentor.instrument_app(app)


class AskRequest(BaseModel):
    prompt: str
    model: str | None = None
    use_tools: bool = False
    use_mcp: bool = False
    conversation_id: str | None = None


class AskResponse(BaseModel):
    result: str
    model: str
    input_tokens: int
    output_tokens: int
    instrumentation: str = "openllmetry"
    provider: str = llm_client.PROVIDER


# ── Traceloop-instrumented building blocks ────────────────────────────────────

@task(name="call_llm")
def call_llm_task(prompt: str, model: str, use_tools: bool = False, use_mcp: bool = False) -> dict:
    try:
        if use_mcp:
            resp = mcp_client.call_llm_with_mcp(client, model, prompt)
        elif use_tools:
            resp = llm_client.call_llm_with_tools(client, model, prompt)
        else:
            resp = llm_client.call_llm(client, model, prompt)
    except Exception as exc:
        span = trace.get_current_span()
        span.set_attribute("exception.type", type(exc).__qualname__)
        span.record_exception(exc)
        raise
    return {
        "content": resp.content,
        "model": resp.model,
        "input_tokens": resp.input_tokens,
        "output_tokens": resp.output_tokens,
    }


@workflow(name="ask_question")
def ask_question(prompt: str, model: str, use_tools: bool = False, use_mcp: bool = False, conversation_id: str = "") -> dict:
    span = trace.get_current_span()
    span.set_attribute("gen_ai.agent.id", "dt-ai-obs-openllmetry-001")
    span.set_attribute("gen_ai.agent.name", "dt-ai-obs-assistant")
    span.set_attribute("gen_ai.agent.version", "0.1.5")
    span.set_attribute("gen_ai.memory.store.id", "in-memory-context-store")
    span.set_attribute("gen_ai.conversation.id", conversation_id)
    return call_llm_task(prompt, model, use_tools, use_mcp)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    conversation_id = req.conversation_id or str(uuid.uuid4())
    logger.info("ask request received prompt_length=%d provider=%s use_tools=%s use_mcp=%s conversation_id=%s", len(req.prompt), llm_client.PROVIDER, req.use_tools, req.use_mcp, conversation_id)
    trace.get_current_span().set_attribute("gen_ai.conversation.id", conversation_id)
    result = ask_question(req.prompt, req.model or MODEL, req.use_tools, req.use_mcp, conversation_id)
    logger.info("llm response model=%s input_tokens=%d output_tokens=%d", result["model"], result["input_tokens"], result["output_tokens"])
    return AskResponse(
        result=result["content"],
        model=result["model"],
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
    )


@app.get("/health")
def health():
    return {"status": "ok", "instrumentation": "openllmetry", "provider": llm_client.PROVIDER}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

"""
Dynatrace AI Observability — MCP (Model Context Protocol) instrumentation test
===============================================================================
Dedicated service that always uses the Dynatrace MCP server to resolve tool
calls, generating real mcp.* OTel span attributes in every request.

The Dynatrace MCP server runs as a subprocess (stdio transport) inside the
container and exposes Dynatrace platform APIs as callable tools.

Run locally (requires Node.js 24 + @dynatrace-oss/dynatrace-mcp-server):
    pip install -r requirements_mcp.txt
    uvicorn app_mcp:app --host 0.0.0.0 --port 8000

Run via docker-compose / podman-compose:
    podman-compose up mcp    # http://localhost:8004/ask

Test:
    curl -s -X POST http://localhost:8004/ask \\
        -H "Content-Type: application/json" \\
        -d '{"prompt": "What are the active problems in this environment?"}' \\
        | python3 -m json.tool

Prerequisites in .env:
    DT_ENDPOINT        — e.g. https://abc12345.live.dynatrace.com
    DT_API_TOKEN       — scopes: openTelemetryTrace.ingest
    DT_PLATFORM_TOKEN  — platform token for MCP server
    DT_APPS_ENDPOINT   — optional; derived from DT_ENDPOINT if unset
    LLM_PROVIDER       — must be anthropic (MCP requires Anthropic SDK)
    ANTHROPIC_API_KEY
    MODEL              — optional; defaults per provider
"""

import os
import uuid
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME as _SVC_NAME_KEY, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace import TracerProvider as _TracerProvider
from pydantic import BaseModel

import llm_client
import log_setup
import mcp_client

load_dotenv()

DT_ENDPOINT = os.environ["DT_ENDPOINT"].rstrip("/")
DT_API_TOKEN = os.environ["DT_API_TOKEN"]
MODEL = llm_client.default_model()
SERVICE = os.getenv("SERVICE_NAME", "dt-ai-obs-mcp")

# ── OTel provider setup ────────────────────────────────────────────────────────

tracer_provider = TracerProvider(
    resource=Resource.create({_SVC_NAME_KEY: SERVICE})
)

exporter = OTLPSpanExporter(
    endpoint=f"{DT_ENDPOINT}/api/v2/otlp/v1/traces",
    headers={"Authorization": f"Api-Token {DT_API_TOKEN}"},
)
tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(tracer_provider)

client = llm_client.create_client()
logger = log_setup.setup_logging(SERVICE, DT_ENDPOINT, DT_API_TOKEN)


# ── FastAPI app ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    tracer_provider.shutdown()


app = FastAPI(title="DT AI Obs — MCP test", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)


class AskRequest(BaseModel):
    prompt: str
    model: str | None = None
    conversation_id: str | None = None


class AskResponse(BaseModel):
    result: str
    model: str
    input_tokens: int
    output_tokens: int
    instrumentation: str = "mcp"
    provider: str = llm_client.PROVIDER


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    conversation_id = req.conversation_id or str(uuid.uuid4())
    logger.info(
        "ask request received prompt_length=%d provider=%s conversation_id=%s",
        len(req.prompt),
        llm_client.PROVIDER,
        conversation_id,
    )
    span = trace.get_current_span()
    span.set_attribute("gen_ai.conversation.id", conversation_id)
    span.set_attribute("session.id", conversation_id)
    span.set_attribute("gen_ai.agent.id", "dt-ai-obs-mcp-001")
    span.set_attribute("gen_ai.agent.name", "dt-ai-obs-assistant")
    span.set_attribute("gen_ai.agent.description", "AI Observability evaluation assistant (MCP)")
    span.set_attribute("gen_ai.agent.version", "0.1.5")
    span.set_attribute("gen_ai.agent.type", "chat_completion")
    span.set_attribute("gen_ai.agent.iteration", 1)
    span.set_attribute("gen_ai.agent.max_iterations", 1)
    span.set_attribute("gen_ai.memory.store.id", "in-memory-context-store")
    span.set_attribute("gen_ai.workflow.name", "ask_question")
    span.set_attribute("gen_ai.conversation.compacted", False)

    try:
        resp = mcp_client.call_llm_with_mcp(client, req.model or MODEL, req.prompt)
    except Exception as exc:
        span.set_attribute("exception.type", type(exc).__qualname__)
        span.set_attribute("error.type", f"{type(exc).__module__}.{type(exc).__qualname__}")
        span.record_exception(exc)
        raise

    logger.info(
        "llm response model=%s input_tokens=%d output_tokens=%d",
        resp.model,
        resp.input_tokens,
        resp.output_tokens,
    )
    return AskResponse(
        result=resp.content,
        model=resp.model,
        input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens,
    )


@app.get("/health")
def health():
    return {"status": "ok", "instrumentation": "mcp", "provider": llm_client.PROVIDER}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

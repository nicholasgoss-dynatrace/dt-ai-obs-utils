"""
Dynatrace AI Observability — OpenInference instrumentation test
===============================================================
Uses openinference-instrumentation-* to auto-instrument the LLM SDK.
OpenInference uses its own attribute conventions (llm.model_name,
llm.token_count.*, etc.), so a normalization step is required before Dynatrace
AI Observability can understand the data.

LLM provider is set via LLM_PROVIDER env var (default: anthropic).
Supported: anthropic, openai. The correct OpenInference instrumentor is
selected automatically based on the provider.

Two normalization options (controlled by OTEL_EXPORTER_OTLP_ENDPOINT):
  A) OTel Collector -- set OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
     (default in podman-compose; the Collector applies the transforms locally)
  B) OpenPipeline   -- set OTEL_EXPORTER_OTLP_ENDPOINT=$DT_ENDPOINT/api/v2/otlp
     (no Collector needed; transforms run server-side in Dynatrace)

Run locally:
    pip install -r requirements_openinference.txt
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
        uvicorn app_openinference:app --host 0.0.0.0 --port 8000

Run via podman-compose:
    podman-compose up openinference otel-collector  # http://localhost:8003/ask

Test:
    curl -s -X POST http://localhost:8003/ask \
        -H "Content-Type: application/json" \
        -d '{"prompt": "What is observability?"}' | python3 -m json.tool

Prerequisites in .env:
    DT_ENDPOINT                  — e.g. https://abc12345.live.dynatrace.com
    DT_API_TOKEN                 — scope: openTelemetryTrace.ingest
    OTEL_EXPORTER_OTLP_ENDPOINT  — Collector URL or DT OTLP endpoint
    LLM_PROVIDER                 — anthropic (default) or openai
    ANTHROPIC_API_KEY / OPENAI_API_KEY
    MODEL                        — optional; defaults per provider if unset
"""

import os
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic import BaseModel

import llm_client
import log_setup

load_dotenv()

DT_ENDPOINT = os.environ["DT_ENDPOINT"].rstrip("/")
DT_API_TOKEN = os.environ["DT_API_TOKEN"]
MODEL = llm_client.default_model()
SERVICE = os.getenv("SERVICE_NAME", os.getenv("OTEL_SERVICE_NAME", "dt-ai-obs-openinference"))

otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
if not otlp_endpoint:
    otlp_endpoint = f"{DT_ENDPOINT}/api/v2/otlp"
    print(f"[INFO] OTEL_EXPORTER_OTLP_ENDPOINT not set; defaulting to {otlp_endpoint}")
    print("[INFO] Ensure OpenPipeline is configured, or set the env var to http://localhost:4318 for OTel Collector mode.")

# OTLPSpanExporter uses the endpoint as-is when passed explicitly — always include /v1/traces.
if not otlp_endpoint.endswith("/v1/traces"):
    otlp_endpoint = otlp_endpoint.rstrip("/") + "/v1/traces"

# ── OTel provider setup ────────────────────────────────────────────────────────

tracer_provider = TracerProvider(
    resource=Resource.create({SERVICE_NAME: SERVICE})
)

exporter = OTLPSpanExporter(
    endpoint=otlp_endpoint,
    headers={"Authorization": f"Api-Token {DT_API_TOKEN}"},
)
tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

# Load the OpenInference instrumentor for the configured provider
if llm_client.PROVIDER == "anthropic":
    from openinference.instrumentation.anthropic import AnthropicInstrumentor
    AnthropicInstrumentor().instrument(tracer_provider=tracer_provider)
elif llm_client.PROVIDER == "openai":
    from openinference.instrumentation.openai import OpenAIInstrumentor
    OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
else:
    raise ValueError(f"No OpenInference instrumentor for provider: {llm_client.PROVIDER!r}")

client = llm_client.create_client()
logger = log_setup.setup_logging(SERVICE, DT_ENDPOINT, DT_API_TOKEN)


# ── FastAPI app ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    tracer_provider.shutdown()


app = FastAPI(title="DT AI Obs — OpenInference test", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)


class AskRequest(BaseModel):
    prompt: str
    model: str | None = None
    use_tools: bool = False


class AskResponse(BaseModel):
    result: str
    model: str
    input_tokens: int
    output_tokens: int
    instrumentation: str = "openinference"
    provider: str = llm_client.PROVIDER


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    """OpenInference instrumentor auto-records the LLM span on every client call."""
    logger.info("ask request received prompt_length=%d provider=%s use_tools=%s", len(req.prompt), llm_client.PROVIDER, req.use_tools)
    span = trace.get_current_span()
    span.set_attribute("gen_ai.agent.id", "dt-ai-obs-openinference-001")
    span.set_attribute("gen_ai.agent.name", "dt-ai-obs-assistant")
    span.set_attribute("gen_ai.agent.version", "0.1.5")
    span.set_attribute("gen_ai.memory.store.id", "in-memory-context-store")
    try:
        if req.use_tools:
            resp = llm_client.call_llm_with_tools(client, req.model or MODEL, req.prompt)
        else:
            resp = llm_client.call_llm(client, req.model or MODEL, req.prompt)
    except Exception as exc:
        trace.get_current_span().record_exception(exc)
        raise
    logger.info("llm response model=%s input_tokens=%d output_tokens=%d", resp.model, resp.input_tokens, resp.output_tokens)
    return AskResponse(
        result=resp.content,
        model=resp.model,
        input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens,
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "instrumentation": "openinference",
        "provider": llm_client.PROVIDER,
        "otlp_endpoint": otlp_endpoint,
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

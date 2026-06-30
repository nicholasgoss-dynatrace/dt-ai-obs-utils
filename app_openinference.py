"""
Dynatrace AI Observability — OpenInference instrumentation test
===============================================================
Uses openinference-instrumentation-openai to auto-instrument the OpenAI SDK.
OpenInference uses its own attribute conventions (llm.model_name,
llm.token_count.*, etc.), so a normalization step is required before Dynatrace
AI Observability can understand the data.

Two normalization options (controlled by OTEL_EXPORTER_OTLP_ENDPOINT):
  A) OTel Collector — set OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
     (default in docker-compose; the Collector applies the transforms locally)
  B) OpenPipeline   — set OTEL_EXPORTER_OTLP_ENDPOINT=$DT_ENDPOINT/api/v2/otlp
     (no Collector needed; transforms run server-side in Dynatrace)

Run locally:
    pip install -r requirements_openinference.txt
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
        uvicorn app_openinference:app --host 0.0.0.0 --port 8000

Run via Docker Compose:
    docker compose up openinference otel-collector  # http://localhost:8003/ask

Test:
    curl -s -X POST http://localhost:8003/ask \
        -H "Content-Type: application/json" \
        -d '{"prompt": "What is observability?"}' | python3 -m json.tool

Prerequisites in .env:
    DT_ENDPOINT                  — e.g. https://abc12345.live.dynatrace.com
    DT_API_TOKEN                 — scope: openTelemetryTrace.ingest
    OTEL_EXPORTER_OTLP_ENDPOINT  — Collector URL or DT OTLP endpoint
    OPENAI_API_KEY
    MODEL                        — e.g. gpt-4o-mini
"""

import os
from contextlib import asynccontextmanager

import openai
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from openinference.instrumentation.openai import OpenAIInstrumentor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic import BaseModel

load_dotenv()

DT_ENDPOINT = os.environ["DT_ENDPOINT"].rstrip("/")
DT_API_TOKEN = os.environ["DT_API_TOKEN"]
MODEL = os.getenv("MODEL", "gpt-4o-mini")
SERVICE = os.getenv("OTEL_SERVICE_NAME", "dt-ai-obs-openinference")

otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
if not otlp_endpoint:
    otlp_endpoint = f"{DT_ENDPOINT}/api/v2/otlp"
    print(f"[INFO] OTEL_EXPORTER_OTLP_ENDPOINT not set; defaulting to {otlp_endpoint}")
    print("[INFO] Ensure OpenPipeline is configured, or set the env var to http://localhost:4318 for OTel Collector mode.")

# ── OTel provider setup ────────────────────────────────────────────────────────

tracer_provider = TracerProvider(
    resource=Resource.create({SERVICE_NAME: SERVICE})
)

exporter = OTLPSpanExporter(
    endpoint=otlp_endpoint,
    headers={"Authorization": f"Api-Token {DT_API_TOKEN}"},
)
tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

# Instrument the OpenAI client — patches all openai.* calls automatically
OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)

client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])


# ── FastAPI app ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Flush remaining spans on shutdown
    tracer_provider.shutdown()


app = FastAPI(title="DT AI Obs — OpenInference test", lifespan=lifespan)


class AskRequest(BaseModel):
    prompt: str


class AskResponse(BaseModel):
    result: str
    model: str
    input_tokens: int
    output_tokens: int
    instrumentation: str = "openinference"


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    """OpenInference auto-records the LLM span when the OpenAI client is called."""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are a concise technical assistant."},
            {"role": "user", "content": req.prompt},
        ],
    )
    return AskResponse(
        result=response.choices[0].message.content,
        model=response.model,
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
    )


@app.get("/health")
def health():
    return {"status": "ok", "instrumentation": "openinference", "otlp_endpoint": otlp_endpoint}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

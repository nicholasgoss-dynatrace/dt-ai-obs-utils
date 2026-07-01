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

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
from traceloop.sdk import Traceloop
from traceloop.sdk.decorators import task, workflow

import llm_client

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

client = llm_client.create_client()
app = FastAPI(title="DT AI Obs — OpenLLMetry test")


class AskRequest(BaseModel):
    prompt: str


class AskResponse(BaseModel):
    result: str
    model: str
    input_tokens: int
    output_tokens: int
    instrumentation: str = "openllmetry"
    provider: str = llm_client.PROVIDER


# ── Traceloop-instrumented building blocks ────────────────────────────────────

@task(name="call_llm")
def call_llm_task(prompt: str) -> dict:
    resp = llm_client.call_llm(client, MODEL, prompt)
    return {
        "content": resp.content,
        "model": resp.model,
        "input_tokens": resp.input_tokens,
        "output_tokens": resp.output_tokens,
    }


@workflow(name="ask_question")
def ask_question(prompt: str) -> dict:
    return call_llm_task(prompt)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    result = ask_question(req.prompt)
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

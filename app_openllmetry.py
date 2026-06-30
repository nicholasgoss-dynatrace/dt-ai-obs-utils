"""
Dynatrace AI Observability — OpenLLMetry instrumentation test
=============================================================
Uses the traceloop-sdk to auto-instrument OpenAI and export
spans + metrics directly to Dynatrace via OTLP.

@workflow  — top-level trace entry (like a "request")
@task      — a named step inside the workflow

Run locally:
    pip install -r requirements_openllmetry.txt
    uvicorn app_openllmetry:app --host 0.0.0.0 --port 8000

Run via Docker Compose:
    docker compose up openllmetry    # http://localhost:8002/ask

Test:
    curl -s -X POST http://localhost:8002/ask \
        -H "Content-Type: application/json" \
        -d '{"prompt": "What is observability?"}' | python3 -m json.tool

Prerequisites in .env:
    DT_ENDPOINT   — e.g. https://abc12345.live.dynatrace.com
    DT_API_TOKEN  — scopes: openTelemetryTrace.ingest, metrics.ingest, logs.ingest
    OPENAI_API_KEY
    MODEL         — e.g. gpt-4o-mini
"""

import os

import openai
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
from traceloop.sdk import Traceloop
from traceloop.sdk.decorators import task, workflow

load_dotenv()

# Required so Dynatrace receives delta metrics (not cumulative)
os.environ["OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE"] = "delta"

DT_ENDPOINT = os.environ["DT_ENDPOINT"].rstrip("/")
DT_API_TOKEN = os.environ["DT_API_TOKEN"]
MODEL = os.getenv("MODEL", "gpt-4o-mini")

Traceloop.init(
    app_name="dt-ai-obs-openllmetry",
    api_endpoint=f"{DT_ENDPOINT}/api/v2/otlp",
    headers={"Authorization": f"Api-Token {DT_API_TOKEN}"},
    disable_batch=True,
)

client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
app = FastAPI(title="DT AI Obs — OpenLLMetry test")


class AskRequest(BaseModel):
    prompt: str


class AskResponse(BaseModel):
    result: str
    model: str
    input_tokens: int
    output_tokens: int
    instrumentation: str = "openllmetry"


# ── Traceloop-instrumented building blocks ────────────────────────────────────

@task(name="call_llm")
def call_llm(messages: list[dict]) -> dict:
    response = client.chat.completions.create(model=MODEL, messages=messages)
    return {
        "content": response.choices[0].message.content,
        "model": response.model,
        "input_tokens": response.usage.prompt_tokens,
        "output_tokens": response.usage.completion_tokens,
    }


@workflow(name="ask_question")
def ask_question(prompt: str) -> dict:
    messages = [
        {"role": "system", "content": "You are a concise technical assistant."},
        {"role": "user", "content": prompt},
    ]
    return call_llm(messages)


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
    return {"status": "ok", "instrumentation": "openllmetry"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

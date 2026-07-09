"""
Dynatrace AI Observability — OneAgent instrumentation test
==========================================================
NO extra instrumentation code is needed here. OneAgent handles everything
automatically once the feature flags are enabled in your Dynatrace tenant.

The FastAPI wrapper is intentional: OneAgent needs an HTTP entry-point span
(from the web framework sensor) so that LLM call spans have a parent to nest
under and appear correctly in AI Observability > Explorer.

LLM provider is set via LLM_PROVIDER env var (default: anthropic).
Supported: anthropic, openai.

Run:
    pip install -r requirements_oneagent.txt
    uvicorn app_oneagent:app --host 0.0.0.0 --port 8000

Then send test requests:
    curl -s -X POST http://localhost:8000/ask \
        -H "Content-Type: application/json" \
        -d '{"prompt": "What is observability?"}'

Required Dynatrace OneAgent feature flags (Settings -> OneAgent features):
    - Python Anthropic (experimental sensor) -- when LLM_PROVIDER=anthropic
    - Python OpenAI (experimental sensor)    -- when LLM_PROVIDER=openai
    - Python FastAPI
"""

import logging
import os

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

import llm_client

load_dotenv()

# OneAgent captures stdout via Log Monitoring and correlates logs to traces natively.
# OTLP log export is not used here — it creates a separate service entity that splits
# logs from the OneAgent-discovered service entity.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("dt-ai-obs-oneagent")

app = FastAPI(title="DT AI Obs — OneAgent test")
client = llm_client.create_client()
MODEL = llm_client.default_model()


class AskRequest(BaseModel):
    prompt: str
    model: str | None = None
    use_tools: bool = False


class AskResponse(BaseModel):
    result: str
    model: str
    input_tokens: int
    output_tokens: int
    instrumentation: str = "oneagent"
    provider: str = llm_client.PROVIDER


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    logger.info("ask request received prompt_length=%d provider=%s use_tools=%s", len(req.prompt), llm_client.PROVIDER, req.use_tools)
    if req.use_tools:
        resp = llm_client.call_llm_with_tools(client, req.model or MODEL, req.prompt)
    else:
        resp = llm_client.call_llm(client, req.model or MODEL, req.prompt)
    logger.info("llm response model=%s input_tokens=%d output_tokens=%d", resp.model, resp.input_tokens, resp.output_tokens)
    return AskResponse(
        result=resp.content,
        model=resp.model,
        input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens,
    )


@app.get("/health")
def health():
    return {"status": "ok", "instrumentation": "oneagent", "provider": llm_client.PROVIDER}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

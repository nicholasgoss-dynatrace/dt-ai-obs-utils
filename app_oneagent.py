"""
Dynatrace AI Observability — OneAgent instrumentation test
==========================================================
NO extra instrumentation code is needed here. OneAgent handles everything
automatically once the feature flags are enabled in your Dynatrace tenant.

The FastAPI wrapper is intentional: OneAgent needs an HTTP entry-point span
(from the web framework sensor) so that LLM call spans have a parent to nest
under and appear correctly in AI Observability > Explorer.

Run:
    pip install -r requirements_oneagent.txt
    uvicorn app_oneagent:app --host 0.0.0.0 --port 8000

Then send test requests:
    curl -s -X POST http://localhost:8000/ask \
        -H "Content-Type: application/json" \
        -d '{"prompt": "What is observability?"}'

Required Dynatrace OneAgent feature flags (Settings → OneAgent features):
    - Python Anthropic (experimental sensor)
    - Python FastAPI
"""

import os

import anthropic
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="DT AI Obs — OneAgent test")
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
MODEL = os.getenv("MODEL", "claude-haiku-4-5-20251001")


class AskRequest(BaseModel):
    prompt: str


class AskResponse(BaseModel):
    result: str
    model: str
    input_tokens: int
    output_tokens: int
    instrumentation: str = "oneagent"


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system="You are a concise technical assistant.",
        messages=[{"role": "user", "content": req.prompt}],
    )
    return AskResponse(
        result=response.content[0].text,
        model=response.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


@app.get("/health")
def health():
    return {"status": "ok", "instrumentation": "oneagent"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

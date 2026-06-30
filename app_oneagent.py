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
"""

import os

import openai
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="DT AI Obs — OneAgent test")
client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
MODEL = os.getenv("MODEL", "gpt-4o-mini")


class AskRequest(BaseModel):
    prompt: str


class AskResponse(BaseModel):
    result: str
    model: str
    input_tokens: int
    output_tokens: int


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": req.prompt}],
    )
    return AskResponse(
        result=response.choices[0].message.content,
        model=response.model,
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
    )


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

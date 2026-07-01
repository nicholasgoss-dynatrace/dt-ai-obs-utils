"""
Shared LLM provider abstraction for the DT AI Obs evaluation tool.

Supported providers (set via LLM_PROVIDER env var, default: anthropic):
  anthropic — uses ANTHROPIC_API_KEY
  openai    — uses OPENAI_API_KEY

Model defaults per provider (override with MODEL env var):
  anthropic → claude-haiku-4-5-20251001
  openai    → gpt-4o-mini
"""

import os
from dataclasses import dataclass

PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()

_MODEL_DEFAULTS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
}


def default_model() -> str:
    return os.getenv("MODEL", _MODEL_DEFAULTS.get(PROVIDER, "gpt-4o-mini"))


def create_client():
    """Return the native SDK client for the configured provider."""
    if PROVIDER == "anthropic":
        import anthropic
        return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    elif PROVIDER == "openai":
        import openai
        return openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    else:
        raise ValueError(
            f"Unsupported LLM_PROVIDER: {PROVIDER!r}. Supported values: 'anthropic', 'openai'."
        )


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int


def call_llm(
    client,
    model: str,
    prompt: str,
    system: str = "You are a concise technical assistant.",
) -> LLMResponse:
    """Call the configured LLM and return a normalized response."""
    if PROVIDER == "anthropic":
        resp = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return LLMResponse(
            content=resp.content[0].text,
            model=resp.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )
    elif PROVIDER == "openai":
        resp = client.chat.completions.create(
            model=model,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return LLMResponse(
            content=resp.choices[0].message.content,
            model=resp.model,
            input_tokens=resp.usage.prompt_tokens,
            output_tokens=resp.usage.completion_tokens,
        )
    else:
        raise ValueError(f"Unsupported PROVIDER in call_llm: {PROVIDER!r}")

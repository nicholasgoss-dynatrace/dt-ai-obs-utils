"""
Shared LLM provider abstraction for the DT AI Obs evaluation tool.

Supported providers (set via LLM_PROVIDER env var, default: anthropic):
  anthropic — uses ANTHROPIC_API_KEY
  openai    — uses OPENAI_API_KEY

Model defaults per provider (override with MODEL env var):
  anthropic → claude-haiku-4-5-20251001
  openai    → gpt-4o-mini
"""

import ast
import json
import operator as op
import os
from dataclasses import dataclass

from opentelemetry import trace as _otel_trace

_tracer = _otel_trace.get_tracer("llm_client")

PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()

_MODEL_DEFAULTS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
}

# ── Tool definitions ──────────────────────────────────────────────────────────

_ANTHROPIC_TOOLS = [
    {
        "name": "calculator",
        "description": "Evaluate arithmetic expressions. Use this when asked to compute a number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Arithmetic expression to evaluate, e.g. '347 * 29 + 15'",
                }
            },
            "required": ["expression"],
        },
    }
]

_OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Evaluate arithmetic expressions. Use this when asked to compute a number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Arithmetic expression to evaluate, e.g. '347 * 29 + 15'",
                    }
                },
                "required": ["expression"],
            },
        },
    }
]

_TOOL_SYSTEM = (
    "You are a concise technical assistant. "
    "Use the calculator tool when asked to compute numbers."
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_SAFE_OPS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Pow: op.pow,
    ast.Mod: op.mod,
    ast.FloorDiv: op.floordiv,
    ast.USub: op.neg,
}


def _safe_eval(expression: str) -> str:
    """Evaluate a simple arithmetic expression without using eval()."""
    def _eval(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        elif isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
            return _SAFE_OPS[type(node.op)](_eval(node.left), _eval(node.right))
        elif isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
            return _SAFE_OPS[type(node.op)](_eval(node.operand))
        raise ValueError(f"Unsupported expression node: {type(node).__name__}")

    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _eval(tree.body)
        return str(round(result, 6) if isinstance(result, float) else result)
    except Exception as exc:
        return f"error: {exc}"


# ── Error helpers ─────────────────────────────────────────────────────────────

def _record_llm_error(exc: Exception) -> None:
    """Set gen_ai.error.code on the current span from a provider exception."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        code = body.get("error", {}).get("type") or body.get("type") or ""
    else:
        code = ""
    if not code:
        code = type(exc).__name__
    span = _otel_trace.get_current_span()
    span.set_attribute("gen_ai.system", PROVIDER)
    span.set_attribute("gen_ai.error.code", code)


# ── Public API ────────────────────────────────────────────────────────────────


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
    temperature: float = 0.7,
    top_p: float = 0.9,
) -> LLMResponse:
    """Call the configured LLM and return a normalized response."""
    try:
        if PROVIDER == "anthropic":
            _otel_trace.get_current_span().set_attribute("gen_ai.request.top_p", top_p)
            resp = client.messages.create(
                model=model,
                max_tokens=1024,
                temperature=temperature,
                stop_sequences=["\n\nHuman:"],
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
                temperature=temperature,
                top_p=top_p,
                stop=["\n\nHuman:"],
                seed=42,
                n=1,
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
    except Exception as exc:
        _record_llm_error(exc)
        raise


def call_llm_with_tools(
    client,
    model: str,
    prompt: str,
    system: str = _TOOL_SYSTEM,
    temperature: float = 0.7,
    top_p: float = 0.9,
) -> LLMResponse:
    """Call the LLM with a calculator tool definition, executing any tool calls."""
    try:
        if PROVIDER == "anthropic":
            _otel_trace.get_current_span().set_attribute("gen_ai.request.top_p", top_p)
            resp = client.messages.create(
                model=model,
                max_tokens=1024,
                temperature=temperature,
                stop_sequences=["\n\nHuman:"],
                system=system,
                tools=_ANTHROPIC_TOOLS,
                messages=[{"role": "user", "content": prompt}],
            )
            total_input = resp.usage.input_tokens
            total_output = resp.usage.output_tokens

            if resp.stop_reason == "tool_use":
                tool_block = next(b for b in resp.content if b.type == "tool_use")
                # Mark the current span as a gen_ai span so DT AI Obs indexes it,
                # then set all tool attributes on it directly.
                cur = _otel_trace.get_current_span()
                cur.set_attribute("gen_ai.system", "anthropic")
                cur.set_attribute("gen_ai.operation.name", "execute_tool")
                cur.set_attribute("gen_ai.tool.name", tool_block.name)
                cur.set_attribute("gen_ai.tool_call.id", tool_block.id)
                cur.set_attribute("gen_ai.tool.description", _ANTHROPIC_TOOLS[0]["description"])
                cur.set_attribute("gen_ai.tool.type", "function")
                with _tracer.start_as_current_span("execute_tool") as tool_span:
                    tool_span.set_attribute("gen_ai.system", "anthropic")
                    tool_span.set_attribute("gen_ai.operation.name", "execute_tool")
                    tool_span.set_attribute("gen_ai.tool.name", tool_block.name)
                    tool_span.set_attribute("gen_ai.tool_call.id", tool_block.id)
                    tool_span.set_attribute("gen_ai.tool.description", _ANTHROPIC_TOOLS[0]["description"])
                    tool_span.set_attribute("gen_ai.tool.type", "function")
                    tool_result = _safe_eval(tool_block.input.get("expression", ""))

                # Serialize content blocks to plain dicts — instrumentation wrappers
                # can make SDK objects non-serializable when passed back to the API.
                assistant_content = []
                for block in resp.content:
                    if block.type == "tool_use":
                        assistant_content.append(
                            {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                        )
                    elif block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})

                resp2 = client.messages.create(
                    model=model,
                    max_tokens=1024,
                    temperature=temperature,
                    stop_sequences=["\n\nHuman:"],
                    system=system,
                    tools=_ANTHROPIC_TOOLS,
                    messages=[
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": assistant_content},
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_block.id,
                                    "content": tool_result,
                                }
                            ],
                        },
                    ],
                )
                total_input += resp2.usage.input_tokens
                total_output += resp2.usage.output_tokens
                text = next((b.text for b in resp2.content if b.type == "text"), "")
                return LLMResponse(
                    content=text,
                    model=resp2.model,
                    input_tokens=total_input,
                    output_tokens=total_output,
                )

            text = next((b.text for b in resp.content if b.type == "text"), "")
            return LLMResponse(
                content=text,
                model=resp.model,
                input_tokens=total_input,
                output_tokens=total_output,
            )

        elif PROVIDER == "openai":
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ]
            resp = client.chat.completions.create(
                model=model,
                max_tokens=1024,
                temperature=temperature,
                top_p=top_p,
                stop=["\n\nHuman:"],
                seed=42,
                n=1,
                tools=_OPENAI_TOOLS,
                messages=messages,
            )
            total_input = resp.usage.prompt_tokens
            total_output = resp.usage.completion_tokens

            if resp.choices[0].finish_reason == "tool_calls":
                tool_call = resp.choices[0].message.tool_calls[0]
                args = json.loads(tool_call.function.arguments)
                cur = _otel_trace.get_current_span()
                cur.set_attribute("gen_ai.system", "openai")
                cur.set_attribute("gen_ai.operation.name", "execute_tool")
                cur.set_attribute("gen_ai.tool.name", tool_call.function.name)
                cur.set_attribute("gen_ai.tool_call.id", tool_call.id)
                cur.set_attribute("gen_ai.tool.description", _OPENAI_TOOLS[0]["function"]["description"])
                cur.set_attribute("gen_ai.tool.type", "function")
                with _tracer.start_as_current_span("execute_tool") as tool_span:
                    tool_span.set_attribute("gen_ai.system", "openai")
                    tool_span.set_attribute("gen_ai.operation.name", "execute_tool")
                    tool_span.set_attribute("gen_ai.tool.name", tool_call.function.name)
                    tool_span.set_attribute("gen_ai.tool_call.id", tool_call.id)
                    tool_span.set_attribute("gen_ai.tool.description", _OPENAI_TOOLS[0]["function"]["description"])
                    tool_span.set_attribute("gen_ai.tool.type", "function")
                    tool_result = _safe_eval(args.get("expression", ""))

                messages.append(resp.choices[0].message)
                messages.append(
                    {"role": "tool", "tool_call_id": tool_call.id, "content": tool_result}
                )
                resp2 = client.chat.completions.create(
                    model=model,
                    max_tokens=1024,
                    temperature=temperature,
                    top_p=top_p,
                    stop=["\n\nHuman:"],
                    seed=42,
                    n=1,
                    tools=_OPENAI_TOOLS,
                    messages=messages,
                )
                total_input += resp2.usage.prompt_tokens
                total_output += resp2.usage.completion_tokens
                return LLMResponse(
                    content=resp2.choices[0].message.content,
                    model=resp2.model,
                    input_tokens=total_input,
                    output_tokens=total_output,
                )

            return LLMResponse(
                content=resp.choices[0].message.content,
                model=resp.model,
                input_tokens=total_input,
                output_tokens=total_output,
            )

        else:
            raise ValueError(f"Unsupported PROVIDER in call_llm_with_tools: {PROVIDER!r}")
    except Exception as exc:
        _record_llm_error(exc)
        raise
